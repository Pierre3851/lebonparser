"""Accès au site web leboncoin via la session d'un navigateur connecté.

Méthode validée : curl_cffi avec empreinte Firefox + cookies extraits du
navigateur (dont le cookie DataDome). Les données sont lues dans le JSON
`__NEXT_DATA__` embarqué dans chaque page (site Next.js).
"""

from __future__ import annotations

import json

from curl_cffi import requests
from parsel import Selector

import config
from cookies import get_leboncoin_cookies
from models import Annonce


def build_session() -> "requests.Session":
    """Session HTTP imitant Firefox, avec les cookies leboncoin du navigateur."""
    jar = get_leboncoin_cookies(config.BROWSER)
    session = requests.Session(impersonate="firefox")
    session.headers["User-Agent"] = config.BROWSER_USER_AGENT
    for name, value in jar.items():
        session.cookies.set(name, value, domain=".leboncoin.fr")
    return session


def _next_data(html: str) -> dict:
    """Extrait et parse le JSON __NEXT_DATA__ d'une page leboncoin."""
    raw = Selector(html).css("script#__NEXT_DATA__::text").get()
    if not raw:
        raise RuntimeError(
            "__NEXT_DATA__ introuvable — la page est probablement un challenge "
            "DataDome. Recharge leboncoin dans le navigateur (connecté) puis réessaie."
        )
    return json.loads(raw)


def _first(value):
    """price est renvoyé sous forme de liste ([69]) ; on prend le 1er élément."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _flatten_attributes(attributes) -> dict:
    """Transforme la liste d'attributs leboncoin en {label/clé: valeur lisible}."""
    out = {}
    for attr in attributes or []:
        if not isinstance(attr, dict):
            continue
        key = attr.get("key_label") or attr.get("key")
        val = attr.get("value_label") or attr.get("value")
        if key and val is not None:
            out[str(key)] = str(val)
    return out


def _ad_summary(ad: dict) -> Annonce:
    """Champs utiles d'une annonce issue de la liste (sans description complète)."""
    loc = ad.get("location") or {}
    images = ad.get("images")
    nb_images = (images or {}).get("nb_images", 0) if isinstance(images, dict) else len(images or [])
    return Annonce(
        id=ad.get("list_id") or ad.get("id"),
        titre=ad.get("subject"),
        prix=_first(ad.get("price")),
        url=ad.get("url"),
        date_publication=ad.get("first_publication_date"),
        categorie=ad.get("category_name"),
        marque=ad.get("brand"),
        ville=loc.get("city_label") or loc.get("city"),
        code_postal=loc.get("zipcode"),
        departement=loc.get("department_name"),
        attributs=_flatten_attributes(ad.get("attributes")),
        nb_images=nb_images,
    )  # description reste None : remplie à l'étape d'enrichissement


def search_page(session, search_url: str, page: int) -> tuple[list[Annonce], int]:
    """Récupère une page de résultats. Retourne (annonces, total)."""
    sep = "&" if "?" in search_url else "?"
    url = f"{search_url}{sep}page={page}"
    resp = session.get(url, timeout=config.HTTP_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} sur la page {page}")
    data = _next_data(resp.text)
    pp = data["props"]["pageProps"]
    search_data = pp.get("searchData") or pp.get("initialProps", {}).get("searchData", {})
    ads = [_ad_summary(a) for a in search_data.get("ads", [])]
    total = search_data.get("total", 0)
    return ads, total


def fetch_body(session, ad_url: str) -> str:
    """Récupère la description complète (body) d'une annonce depuis sa page."""
    resp = session.get(ad_url, timeout=config.HTTP_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} sur {ad_url}")
    data = _next_data(resp.text)
    ad = data["props"]["pageProps"].get("ad") or {}
    return ad.get("body") or ""
