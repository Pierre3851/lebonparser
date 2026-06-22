"""Récupération des cookies leboncoin depuis le navigateur Firefox.

Permet de réutiliser une session DataDome valide (et la connexion au compte)
issue d'un vrai navigateur, conformément à la recommandation officielle de la
librairie `lbc` : en cas de 403, copier le cookie DataDome du navigateur.
"""

from __future__ import annotations

import browser_cookie3


def get_leboncoin_cookies(browser: str = "firefox") -> dict[str, str]:
    """Retourne {nom: valeur} des cookies leboncoin.fr du navigateur indiqué."""
    loader = getattr(browser_cookie3, browser, None)
    if loader is None:
        raise ValueError(f"Navigateur non supporté : {browser}")
    jar = loader(domain_name="leboncoin.fr")
    cookies = {c.name: c.value for c in jar}
    if "datadome" not in cookies:
        raise RuntimeError(
            "Cookie 'datadome' introuvable. Ouvre leboncoin.fr dans "
            f"{browser} (connecté), accepte/charge une page, puis réessaie."
        )
    return cookies


if __name__ == "__main__":
    c = get_leboncoin_cookies()
    print(f"{len(c)} cookies récupérés. datadome présent : {'datadome' in c}")
