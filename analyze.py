"""Analyse des annonces par le LLM.

Pour CHAQUE annonce :
  1. télécharge le texte intégral (description complète sur la page de détail) ;
  2. le fait juger par le LLM (sortie structurée {interessant, score, raison}) ;
  3. renseigne score / interessant / raison sur l'annonce (modifiée sur place).

Deux régimes d'exécution, selon `config.LLM_BACKEND` :
  - "ollama" : séquentiel et entrelacé. La latence d'inférence du LLM espace
    naturellement les requêtes vers leboncoin (un plancher MIN_FETCH_INTERVAL
    garantit un rythme doux même si l'inférence est rapide).
  - "api" : DEUX phases. Phase A — téléchargement des descriptions, SÉQUENTIEL et
    throttlé (anti-DataDome, car c'est le seul accès à leboncoin). Phase B —
    jugement EN PARALLÈLE via le LLM distant (aucun accès à leboncoin, donc
    parallélisable sans risque). C'est là que l'API fait gagner du temps.

Module utilisé par core.run_search ; `analyser_liste()` est l'entrée principale.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time

import config
import llm
import web

log = logging.getLogger("lebonparser")


def _useful_attributes(attributs: dict) -> dict:
    """Ne garde que les attributs lisibles (ex: 'État', 'Univers'), pas le bruit
    technique (rating_score, profile_picture_url, shipping_type, booléens...)."""
    out = {}
    for key, val in (attributs or {}).items():
        if val in ("true", "false") or str(val).startswith("http"):
            continue
        if any(c.isupper() or ord(c) > 127 for c in key):
            out[key] = val
    return out


def _full_text(ad: dict) -> str:
    """Texte intégral (titre + prix + lieu + attributs utiles + description)."""
    lignes = [
        f"Titre : {ad.get('titre')}",
        f"Prix : {ad.get('prix')} €",
        f"Lieu : {ad.get('ville')}",
    ]
    for k, v in _useful_attributes(ad.get("attributs")).items():
        lignes.append(f"{k} : {v}")
    lignes.append(f"\nDescription :\n{ad.get('description') or ''}")
    return "\n".join(lignes)


def _fetch_description(session, ad: dict, index: int, total: int) -> None:
    """Étape 1 : télécharge le texte intégral de l'annonce (accès réseau leboncoin)."""
    log.info("[%d/%d] %s — %s €", index, total, ad.get("titre"), ad.get("prix"))
    log.info("        url : %s", ad.get("url"))
    try:
        ad["description"] = web.fetch_body(session, ad["url"])
        log.info("        texte récupéré (%d caractères)", len(ad["description"]))
    except Exception as exc:  # noqa: BLE001
        ad["description"] = ""
        log.warning("        échec téléchargement : %s: %s", type(exc).__name__, exc)


def _judge_description(ad: dict, index: int, total: int, critere: str) -> bool:
    """Étape 2-3 : juge l'annonce déjà téléchargée (appel LLM). Retourne True si retenue.

    `critere` : critère de filtrage en langage naturel (propre à la recherche)."""
    texte = _full_text(ad)
    log.debug("        --- texte envoyé au LLM ---\n%s\n        ---------------------------", texte)
    try:
        j, raisonnement = llm.judge(texte, critere)
        ad["score"], ad["interessant"], ad["raison"] = j.score, j.interessant, j.raison
        ad["erreur"] = False
        if raisonnement:
            log.debug("        --- raisonnement (thinking) ---\n%s\n        ---------------------------", raisonnement)
        log.debug("        réponse LLM : %s", j.model_dump_json())
    except Exception as exc:  # noqa: BLE001
        # Marqué erreur : sera rejugé au prochain run (pas figé à score 0 dans seen.json).
        ad["score"], ad["interessant"], ad["raison"], ad["erreur"] = 0, False, "erreur d'analyse", True
        log.warning("        échec jugement : %s: %s", type(exc).__name__, exc)

    retenue = ad["score"] >= config.SCORE_MIN
    log.info(
        "        verdict : %s  score %d/10 — %s",
        "RETENUE ✓" if retenue else "écartée",
        ad["score"],
        ad["raison"],
    )
    return retenue


def analyser_annonce(session, ad: dict, index: int, total: int, critere: str) -> bool:
    """Traite une annonce (télécharge puis juge). Retourne True si retenue."""
    _fetch_description(session, ad, index, total)
    return _judge_description(ad, index, total, critere)


def analyser_liste(session, ads: list[dict], critere: str,
                   skip_ids: set | None = None, progress_cb=None) -> list[dict]:
    """Juge les annonces de `ads` non encore vues (id absent de `skip_ids`).

    Chaque annonce jugée est modifiée sur place (score/interessant/raison/description).
    `progress_cb(i, total, ad)` est appelé après chaque annonce (pour l'UI / sauvegarde) ;
    `i` est le nombre d'annonces terminées (ordre non garanti en mode parallèle).
    Renvoie la liste des annonces effectivement jugées (les nouvelles)."""
    skip_ids = skip_ids or set()
    a_juger = [ad for ad in ads if str(ad.get("id")) not in skip_ids]
    total = len(a_juger)
    if config.LLM_BACKEND == "api" and config.LLM_CONCURRENCY > 1 and total > 1:
        _analyser_parallele(session, a_juger, critere, total, progress_cb)
    else:
        _analyser_sequentiel(session, a_juger, critere, total, progress_cb)
    return a_juger


def _analyser_sequentiel(session, a_juger: list[dict], critere: str,
                         total: int, progress_cb) -> None:
    """Téléchargement + jugement entrelacés, une annonce à la fois (backend Ollama)."""
    for i, ad in enumerate(a_juger, 1):
        t0 = time.monotonic()
        analyser_annonce(session, ad, i, total, critere)
        if progress_cb:
            progress_cb(i, total, ad)
        # Plancher de sécurité entre deux requêtes réseau.
        if i < total:
            reste = config.MIN_FETCH_INTERVAL - (time.monotonic() - t0)
            if reste > 0:
                time.sleep(reste)


def _analyser_parallele(session, a_juger: list[dict], critere: str,
                        total: int, progress_cb) -> None:
    """Phase A (téléchargement séquentiel throttlé) puis Phase B (jugement parallèle).

    Seul le jugement LLM (appels API, sans accès leboncoin) est parallélisé : le
    téléchargement reste séquentiel pour ne pas déclencher DataDome."""
    # --- Phase A : téléchargement SÉQUENTIEL et throttlé (anti-DataDome) ---
    # On NE notifie PAS progress_cb ici : core l'utilise pour sauvegarder seen.json,
    # et une annonce pas encore jugée donnerait un enregistrement incomplet (score 0,
    # sans verdict). Tant qu'une annonce n'est pas jugée (Phase B), rien n'est persisté :
    # un crash en Phase A → ces annonces sont simplement rejugées au prochain run.
    log.info("Phase A : téléchargement de %d description(s) (séquentiel)…", total)
    for i, ad in enumerate(a_juger, 1):
        t0 = time.monotonic()
        _fetch_description(session, ad, i, total)
        if i < total:
            reste = config.MIN_FETCH_INTERVAL - (time.monotonic() - t0)
            if reste > 0:
                time.sleep(reste)

    # --- Phase B : jugement LLM EN PARALLÈLE ---
    log.info("Phase B : jugement de %d annonce(s) (%d en parallèle)…",
             total, config.LLM_CONCURRENCY)
    done = 0
    lock = threading.Lock()

    def _work(item):
        i, ad = item
        _judge_description(ad, i, total, critere)
        return ad

    with concurrent.futures.ThreadPoolExecutor(max_workers=config.LLM_CONCURRENCY) as ex:
        futures = [ex.submit(_work, (i, ad)) for i, ad in enumerate(a_juger, 1)]
        for fut in concurrent.futures.as_completed(futures):
            ad = fut.result()
            # Sérialise les effets de bord (sauvegarde seen.json + progression) :
            # progress_cb n'est donc jamais appelé par deux threads à la fois.
            with lock:
                done += 1
                if progress_cb:
                    progress_cb(done, total, ad)
