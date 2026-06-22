"""Analyse des annonces par le LLM local, en une passe (flux).

Pour CHAQUE annonce :
  1. télécharge le texte intégral (description complète sur la page de détail) ;
  2. le fait juger par le LLM (sortie structurée {interessant, score, raison}) ;
  3. renseigne score / interessant / raison sur l'annonce (modifiée sur place).

La latence d'inférence du LLM espace naturellement les requêtes vers leboncoin ;
un plancher (MIN_FETCH_INTERVAL) garantit un rythme doux même si l'inférence est rapide.

Module utilisé par core.run_search ; `analyser_liste()` est l'entrée principale.
"""

from __future__ import annotations

import logging
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


def analyser_annonce(session, ad: dict, index: int, total: int, critere: str) -> bool:
    """Traite une annonce (télécharge, juge, journalise). Retourne True si retenue.

    `critere` : critère de filtrage en langage naturel (propre à la recherche)."""
    log.info("[%d/%d] %s — %s €", index, total, ad.get("titre"), ad.get("prix"))
    log.info("        url : %s", ad.get("url"))

    # 1. Texte intégral
    try:
        ad["description"] = web.fetch_body(session, ad["url"])
        log.info("        texte récupéré (%d caractères)", len(ad["description"]))
    except Exception as exc:  # noqa: BLE001
        ad["description"] = ""
        log.warning("        échec téléchargement : %s: %s", type(exc).__name__, exc)

    # 2. Jugement LLM (le texte intégral envoyé n'apparaît que dans le fichier)
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

    # 3. Verdict
    retenue = ad["score"] >= config.SCORE_MIN
    log.info(
        "        verdict : %s  score %d/10 — %s",
        "RETENUE ✓" if retenue else "écartée",
        ad["score"],
        ad["raison"],
    )
    return retenue


def analyser_liste(session, ads: list[dict], critere: str,
                   skip_ids: set | None = None, progress_cb=None) -> list[dict]:
    """Juge les annonces de `ads` non encore vues (id absent de `skip_ids`).

    Chaque annonce jugée est modifiée sur place (score/interessant/raison/description).
    `progress_cb(i, total, ad)` est appelé après chaque annonce (pour l'UI / sauvegarde).
    Renvoie la liste des annonces effectivement jugées (les nouvelles)."""
    skip_ids = skip_ids or set()
    a_juger = [ad for ad in ads if str(ad.get("id")) not in skip_ids]
    total = len(a_juger)
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
    return a_juger
