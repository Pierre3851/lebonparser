"""Analyse des annonces par le LLM.

Pour CHAQUE annonce :
  1. télécharge le texte intégral (description complète sur la page de détail) ;
  2. le fait juger par le LLM (sortie structurée {interessant, score, raison}) ;
  3. renseigne score / interessant / raison sur l'annonce (modifiée sur place).

Deux régimes d'exécution, selon `config.LLM_BACKEND` :
  - "ollama" : séquentiel et entrelacé. La latence d'inférence du LLM espace
    naturellement les requêtes vers leboncoin (un plancher MIN_FETCH_INTERVAL
    garantit un rythme doux même si l'inférence est rapide).
  - "api" : PIPELINE producteur/consommateur. UN producteur télécharge les
    descriptions SÉQUENTIELLEMENT et throttlé (anti-DataDome, car c'est le seul
    accès à leboncoin) et les pousse au fil de l'eau dans une file ; N=LLM_CONCURRENCY
    consommateurs jugent EN PARALLÈLE via le LLM distant (aucun accès à leboncoin)
    les annonces déjà téléchargées. Téléchargement et jugement se RECOUVRENT (max
    des deux) au lieu de s'additionner. C'est là que l'API fait gagner du temps.

Module utilisé par core.run_search ; `analyser_liste()` est l'entrée principale.
"""

from __future__ import annotations

import logging
import queue
import threading
import time

import config
import llm
import web
from models import Annonce, Progress

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


def _full_text(ad: Annonce) -> str:
    """Texte intégral (titre + prix + lieu + attributs utiles + description)."""
    lignes = [
        f"Titre : {ad.titre}",
        f"Prix : {ad.prix} €",
        f"Lieu : {ad.ville}",
    ]
    for k, v in _useful_attributes(ad.attributs).items():
        lignes.append(f"{k} : {v}")
    lignes.append(f"\nDescription :\n{ad.description or ''}")
    return "\n".join(lignes)


def _throttle(t0: float) -> None:
    """Respecte le plancher anti-DataDome (MIN_FETCH_INTERVAL) depuis l'instant `t0`."""
    reste = config.MIN_FETCH_INTERVAL - (time.monotonic() - t0)
    if reste > 0:
        time.sleep(reste)


def _fetch_description(session, ad: Annonce, index: int, total: int) -> None:
    """Étape 1 : télécharge le texte intégral de l'annonce (accès réseau leboncoin)."""
    log.info("[%d/%d] %s — %s €", index, total, ad.titre, ad.prix)
    log.info("        url : %s", ad.url)
    try:
        ad.description = web.fetch_body(session, ad.url)
        log.info("        texte récupéré (%d caractères)", len(ad.description))
    except Exception as exc:  # noqa: BLE001
        ad.description = ""
        log.warning("        échec téléchargement : %s: %s", type(exc).__name__, exc)


def _judge_description(ad: Annonce, index: int, total: int, critere: str) -> bool:
    """Étape 2-3 : juge l'annonce déjà téléchargée (appel LLM). Retourne True si retenue.

    `critere` : critère de filtrage en langage naturel (propre à la recherche)."""
    texte = _full_text(ad)
    log.debug("        --- texte envoyé au LLM ---\n%s\n        ---------------------------", texte)
    try:
        j, raisonnement = llm.judge(texte, critere)
        ad.score, ad.interessant, ad.raison = j.score, j.interessant, j.raison
        ad.erreur = False
        if raisonnement:
            log.debug("        --- raisonnement (thinking) ---\n%s\n        ---------------------------", raisonnement)
        log.debug("        réponse LLM : %s", j.model_dump_json())
    except Exception as exc:  # noqa: BLE001
        # Marqué erreur : sera rejugé au prochain run (pas figé à score 0 dans seen.json).
        ad.score, ad.interessant, ad.raison, ad.erreur = 0, False, "erreur d'analyse", True
        log.warning("        échec jugement : %s: %s", type(exc).__name__, exc)

    retenue = ad.score >= config.SCORE_MIN
    log.info(
        "        verdict : %s  score %d/10 — %s",
        "RETENUE ✓" if retenue else "écartée",
        ad.score,
        ad.raison,
    )
    return retenue


def analyser_annonce(session, ad: Annonce, index: int, total: int, critere: str) -> bool:
    """Traite une annonce (télécharge puis juge). Retourne True si retenue."""
    _fetch_description(session, ad, index, total)
    return _judge_description(ad, index, total, critere)


def analyser_liste(session, ads: list[Annonce], critere: str,
                   skip_ids: set | None = None, progress_cb=None) -> list[Annonce]:
    """Juge les annonces de `ads` non encore vues (id absent de `skip_ids`).

    Chaque annonce jugée est modifiée sur place (score/interessant/raison/description).
    `progress_cb(Progress)` est appelé après chaque annonce (pour l'UI / sauvegarde),
    avec `item` = l'annonce jugée ; `current` = le nombre d'annonces terminées (ordre
    non garanti en mode parallèle). Renvoie la liste des annonces effectivement jugées.

    Le régime (séquentiel ou parallèle) découle de llm.max_concurrency() : l'appelant
    n'a pas à connaître le backend."""
    skip_ids = skip_ids or set()
    a_juger = [ad for ad in ads if ad.id_str not in skip_ids]
    total = len(a_juger)
    if llm.max_concurrency() > 1 and total > 1:
        _analyser_parallele(session, a_juger, critere, total, progress_cb)
    else:
        _analyser_sequentiel(session, a_juger, critere, total, progress_cb)
    return a_juger


def _notify(progress_cb, done: int, total: int, ad: Annonce) -> None:
    if progress_cb:
        progress_cb(Progress("analyse", done, total, f"Analyse {done}/{total} — {ad.titre}", item=ad))


def _analyser_sequentiel(session, a_juger: list[Annonce], critere: str,
                         total: int, progress_cb) -> None:
    """Téléchargement + jugement entrelacés, une annonce à la fois (backend Ollama)."""
    for i, ad in enumerate(a_juger, 1):
        t0 = time.monotonic()
        analyser_annonce(session, ad, i, total, critere)
        _notify(progress_cb, i, total, ad)
        if i < total:  # plancher de sécurité entre deux requêtes réseau
            _throttle(t0)


def _analyser_parallele(session, a_juger: list[Annonce], critere: str,
                        total: int, progress_cb) -> None:
    """Pipeline producteur/consommateur : le téléchargement et le jugement se recouvrent.

    UN producteur télécharge les descriptions SÉQUENTIELLEMENT et throttlé (c'est le
    seul accès à leboncoin → anti-DataDome) et pousse chaque annonce prête dans une
    file. N=LLM_CONCURRENCY consommateurs jugent EN PARALLÈLE (appels LLM, sans accès
    leboncoin) les annonces déjà téléchargées. Durée ≈ max(téléchargement, jugement)
    au lieu de leur somme.

    Le producteur NE notifie PAS progress_cb (core s'en sert pour persister seen.json :
    une annonce pas encore jugée donnerait un enregistrement incomplet). Seul le
    consommateur notifie, après le verdict — donc tant qu'une annonce n'est pas jugée,
    rien n'est persisté, et un crash en téléchargement la fait simplement rejuger au
    prochain run."""
    workers = llm.max_concurrency()
    log.info("Pipeline : 1 téléchargeur (séquentiel) → %d juge(s) en parallèle, %d annonce(s).",
             workers, total)

    file: queue.Queue = queue.Queue()
    done = 0
    lock = threading.Lock()

    def producteur() -> None:
        # Téléchargement SÉQUENTIEL throttlé ; chaque annonce prête part aussitôt au
        # jugement. Le finally garantit l'envoi des sentinelles même en cas d'imprévu,
        # pour que les consommateurs ne restent jamais bloqués sur la file.
        try:
            for i, ad in enumerate(a_juger, 1):
                t0 = time.monotonic()
                _fetch_description(session, ad, i, total)
                file.put((i, ad))
                if i < total:
                    _throttle(t0)
        finally:
            for _ in range(workers):  # une sentinelle d'arrêt par consommateur
                file.put(None)

    def consommateur() -> None:
        nonlocal done
        while True:
            item = file.get()
            if item is None:  # sentinelle : plus rien à juger
                return
            i, ad = item
            _judge_description(ad, i, total, critere)
            # Sérialise les effets de bord (sauvegarde seen.json + progression) :
            # progress_cb n'est jamais appelé par deux threads à la fois.
            with lock:
                done += 1
                _notify(progress_cb, done, total, ad)

    consommateurs = [threading.Thread(target=consommateur, daemon=True) for _ in range(workers)]
    for t in consommateurs:
        t.start()
    producteur()  # tourne dans le thread courant : sa fin pousse les sentinelles
    for t in consommateurs:
        t.join()
