"""Récupère la LISTE de toutes les annonces d'une recherche leboncoin.

Méthode : site web leboncoin + session navigateur connectée (voir web.py).
La liste fournit titre, prix, lieu, attributs et URL — mais PAS la description
complète (récupérée plus tard, par annonce, via web.fetch_body lors de l'analyse).

Module utilisé par core.run_search ; `scrape()` est la seule entrée publique.
"""

from __future__ import annotations

import logging
import math
import random
import time

import config
import web

log = logging.getLogger("lebonparser")


def scrape(session, search_url: str, progress_cb=None) -> list[dict]:
    """Parcourt toutes les pages d'une recherche et renvoie les annonces dédoublonnées.

    `session`     : session HTTP (web.build_session()).
    `search_url`  : URL de la recherche leboncoin.
    `progress_cb` : callback optionnel progress_cb(page, nb_pages, cumul) pour l'UI.
    """
    log.info("Recherche : %s", search_url)

    ads, total = web.search_page(session, search_url, page=1)
    nb_pages = min(math.ceil(total / config.PAGE_SIZE), config.MAX_PAGES)
    log.info("%d annonces au total → %d page(s) à parcourir.", total, nb_pages)
    if progress_cb:
        progress_cb(1, nb_pages, len(ads))

    for page in range(2, nb_pages + 1):
        time.sleep(random.uniform(*config.DELAY_BETWEEN_PAGES))
        page_ads, _ = web.search_page(session, search_url, page=page)
        ads.extend(page_ads)
        log.debug("page %d/%d : %d annonces (cumul %d).", page, nb_pages, len(page_ads), len(ads))
        if progress_cb:
            progress_cb(page, nb_pages, len(ads))

    # Dédoublonnage par id.
    seen, unique = set(), []
    for ad in ads:
        if ad["id"] not in seen:
            seen.add(ad["id"])
            unique.append(ad)
    return unique
