"""Cœur métier multi-recherches : stockage des recherches et exécution incrémentale.

Chaque recherche enregistrée vit dans son propre dossier sous `searches/` :

    searches/<slug>/
        search.json   # {name, slug, url, critere, created, last_run}
        seen.json     # {ad_id: {...}} — mémoire de TOUTES les annonces déjà vues/jugées
        analyse.log   # journal du dernier run

`seen.json` est la mémoire centrale : une annonce déjà présente n'est jamais rejugée.
Un run quotidien ne fait donc tourner le LLM que sur les nouvelles annonces.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import shutil
import time
import unicodedata
from datetime import datetime

import config
import scraper
import analyze
import llm
import web

SEARCHES_DIR = "searches"
log = logging.getLogger("lebonparser")


# --------------------------------------------------------------------------- #
# Stockage des recherches
# --------------------------------------------------------------------------- #

def slugify(name: str) -> str:
    """Transforme un nom libre en identifiant de dossier (kebab-case ASCII)."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "recherche"


def _dir(slug: str) -> str:
    return os.path.join(SEARCHES_DIR, slug)


def _search_file(slug: str) -> str:
    return os.path.join(_dir(slug), "search.json")


def _seen_file(slug: str) -> str:
    return os.path.join(_dir(slug), "seen.json")


def _log_file(slug: str) -> str:
    return os.path.join(_dir(slug), "analyse.log")


def list_searches() -> list[dict]:
    """Toutes les recherches enregistrées (triées par nom)."""
    if not os.path.isdir(SEARCHES_DIR):
        return []
    out = []
    for slug in os.listdir(SEARCHES_DIR):
        if os.path.isfile(_search_file(slug)):
            out.append(load_search(slug))
    out.sort(key=lambda s: (s.get("name") or "").lower())
    return out


def _clean_urls(urls: list[str]) -> list[str]:
    """Nettoie + dédoublonne les URL en conservant l'ordre."""
    out = []
    for u in urls:
        u = (u or "").strip()
        if u and u not in out:
            out.append(u)
    return out


def _normalize(search: dict) -> dict:
    """Garantit la présence de `urls` (liste). Migre l'ancien champ `url` (chaîne)."""
    if "urls" not in search:
        legacy = search.get("url")
        search["urls"] = [legacy] if legacy else []
    search.pop("url", None)
    return search


def load_search(slug: str) -> dict:
    with open(_search_file(slug), encoding="utf-8") as f:
        return _normalize(json.load(f))


def save_search(search: dict) -> None:
    os.makedirs(_dir(search["slug"]), exist_ok=True)
    with open(_search_file(search["slug"]), "w", encoding="utf-8") as f:
        json.dump(search, f, ensure_ascii=False, indent=2)


def create_search(name: str, urls: list[str], critere: str) -> dict:
    """Crée une recherche avec un slug unique et la sauvegarde."""
    base = slugify(name)
    slug, n = base, 2
    while os.path.isdir(_dir(slug)):
        slug, n = f"{base}-{n}", n + 1
    search = {
        "name": name.strip(),
        "slug": slug,
        "urls": _clean_urls(urls),
        "critere": critere.strip(),
        "created": datetime.now().isoformat(timespec="seconds"),
        "last_run": None,
    }
    save_search(search)
    return search


def update_search(slug: str, name: str, urls: list[str], critere: str) -> dict:
    """Met à jour le nom/les URL/le critère d'une recherche existante (slug inchangé)."""
    search = load_search(slug)
    search["name"] = name.strip()
    search["urls"] = _clean_urls(urls)
    search["critere"] = critere.strip()
    save_search(search)
    return search


def delete_search(slug: str) -> None:
    if not os.path.isdir(_dir(slug)):
        return
    # Le journal de ce slug est peut-être encore ouvert (run précédent) : on le ferme
    # avant rmtree, sinon Windows refuse la suppression (fichier verrouillé).
    target = os.path.abspath(_log_file(slug))
    for h in list(log.handlers):
        if getattr(h, "baseFilename", None) == target:
            h.close()
            log.removeHandler(h)
    shutil.rmtree(_dir(slug))


def load_seen(slug: str) -> dict:
    try:
        with open(_seen_file(slug), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_seen(slug: str, seen: dict) -> None:
    os.makedirs(_dir(slug), exist_ok=True)
    with open(_seen_file(slug), "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def search_stats(slug: str) -> dict:
    """Compteurs pour l'affichage de la liste (annonces vues / retenues)."""
    seen = load_seen(slug)
    retenues = sum(1 for v in seen.values() if v.get("score", 0) >= config.SCORE_MIN)
    return {"n_seen": len(seen), "n_retenues": retenues}


def retenues(slug: str) -> list[dict]:
    """Historique : annonces retenues (score >= SCORE_MIN), triées par score."""
    seen = load_seen(slug)
    out = [v for v in seen.values() if v.get("score", 0) >= config.SCORE_MIN]
    out.sort(key=lambda a: a.get("score", 0), reverse=True)
    return out


def nouveautes(slug: str) -> list[dict]:
    """Annonces retenues lors du DERNIER run (date_found == last_run)."""
    search = load_search(slug)
    ref = search.get("last_run")
    if not ref:
        return []
    out = [
        v for v in load_seen(slug).values()
        if v.get("date_found") == ref and v.get("score", 0) >= config.SCORE_MIN
    ]
    out.sort(key=lambda a: a.get("score", 0), reverse=True)
    return out


# --------------------------------------------------------------------------- #
# Exécution d'une recherche
# --------------------------------------------------------------------------- #

def _close_logging() -> None:
    """Ferme et détache les handlers (libère le fichier journal sous Windows)."""
    for h in list(log.handlers):
        try:
            h.close()
        finally:
            log.removeHandler(h)


def _setup_logging(slug: str) -> None:
    """Journal du run dans searches/<slug>/analyse.log (neuf à chaque run) + console."""
    log.setLevel(logging.DEBUG)
    _close_logging()  # ferme proprement les handlers d'un run précédent
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    fichier = logging.FileHandler(_log_file(slug), mode="w", encoding="utf-8")
    fichier.setLevel(logging.DEBUG)
    fichier.setFormatter(fmt)
    log.addHandler(console)
    log.addHandler(fichier)


def _record(ad: dict, run_ts: str) -> dict:
    """Enregistrement minimal et stable d'une annonce jugée pour seen.json."""
    return {
        "id": str(ad.get("id")),
        "titre": ad.get("titre"),
        "url": ad.get("url"),
        "prix": ad.get("prix"),
        "ville": ad.get("ville"),
        "description": ad.get("description") or "",
        "score": ad.get("score", 0),
        "interessant": ad.get("interessant", False),
        "raison": ad.get("raison", ""),
        "erreur": bool(ad.get("erreur", False)),
        "date_found": run_ts,
    }


def _en_erreur(rec: dict) -> bool:
    """Une annonce déjà vue dont le jugement avait échoué (à rejuger).
    Gère aussi les anciennes entrées sans le champ 'erreur'."""
    return bool(rec.get("erreur")) or rec.get("raison") == "erreur d'analyse"


def run_search(slug: str, progress_cb=None) -> dict:
    """Exécute une recherche : scrape la liste complète, ne juge que les NOUVELLES
    annonces, met à jour seen.json, et renvoie un résumé du run.

    `progress_cb(dict)` reçoit {phase, current, total, message} pour l'UI.
    Lève une exception en cas d'échec (DataDome, Ollama injoignable...) ; l'appelant
    (app.py) la convertit en message d'erreur affichable.
    """
    search = load_search(slug)
    _setup_logging(slug)
    try:
        run_ts = datetime.now().isoformat(timespec="seconds")
        log.info("=== Run « %s » — %s ===", search["name"], run_ts)

        llm.check_ready()  # échoue vite et clairement si Ollama/modèle absent
        session = web.build_session()
        seen = load_seen(slug)

        # 1. Scraping : une recherche peut couvrir plusieurs URL (sections leboncoin).
        #    On parcourt chaque source et on fusionne les annonces en dédoublonnant
        #    par id (une même annonce peut figurer dans plusieurs sections).
        urls = search.get("urls") or []
        ads, vus_run = [], set()
        for src, url in enumerate(urls, 1):
            def _scrape_progress(page, nb_pages, cumul, _src=src):
                if progress_cb:
                    src_txt = f"Source {_src}/{len(urls)} — " if len(urls) > 1 else ""
                    progress_cb({
                        "phase": "scraping", "current": page, "total": nb_pages,
                        "message": f"{src_txt}page {page}/{nb_pages} — {cumul} annonces",
                    })

            for ad in scraper.scrape(session, url, progress_cb=_scrape_progress):
                aid = str(ad.get("id"))
                if aid not in vus_run:
                    vus_run.add(aid)
                    ads.append(ad)

            if src < len(urls):  # délai anti-DataDome entre deux sources
                time.sleep(random.uniform(*config.DELAY_BETWEEN_PAGES))

        # 2. Diff : on juge les annonces jamais vues + celles dont le jugement
        #    précédent avait échoué (rejugées tant qu'elles réapparaissent).
        nouveaux = [
            a for a in ads
            if str(a.get("id")) not in seen or _en_erreur(seen[str(a.get("id"))])
        ]
        log.info("%d annonces au total, %d à analyser (nouvelles + erreurs précédentes).",
                 len(ads), len(nouveaux))
        if progress_cb:
            progress_cb({
                "phase": "analyse", "current": 0, "total": len(nouveaux),
                "message": f"{len(nouveaux)} nouvelle(s) annonce(s) à analyser",
            })

        # 3. Analyse LLM des seules nouvelles annonces, avec sauvegarde incrémentale.
        def _judge_progress(i, total, ad):
            seen[str(ad.get("id"))] = _record(ad, run_ts)
            save_seen(slug, seen)  # incrémental : un crash ne perd pas le travail fait
            if progress_cb:
                progress_cb({
                    "phase": "analyse", "current": i, "total": total,
                    "message": f"Analyse {i}/{total} — {ad.get('titre')}",
                })

        analyze.analyser_liste(session, nouveaux, search["critere"], progress_cb=_judge_progress)

        # 4. Finalisation.
        search["last_run"] = run_ts
        save_search(search)
        save_seen(slug, seen)

        retenus_new = [
            v for v in seen.values()
            if v.get("date_found") == run_ts and v.get("score", 0) >= config.SCORE_MIN
        ]
        retenus_new.sort(key=lambda a: a.get("score", 0), reverse=True)
        log.info(
            "=== Terminé : %d nouvelles, %d retenues (score >= %d) ===",
            len(nouveaux), len(retenus_new), config.SCORE_MIN,
        )
        return {
            "run_ts": run_ts,
            "n_scraped": len(ads),
            "n_new": len(nouveaux),
            "n_retenues_new": len(retenus_new),
            "nouveaux_retenus": retenus_new,
        }
    finally:
        _close_logging()  # libère analyse.log (sinon verrouillé sous Windows)
