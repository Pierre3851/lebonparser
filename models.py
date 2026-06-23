"""Types de données partagés du pipeline.

Deux structures circulent entre les modules :
  - `Annonce` : une annonce leboncoin, de la liste de résultats au jugement LLM ;
  - `Progress` : un événement de progression, émis par scraper/analyze vers l'UI.

Ce module ne dépend d'AUCUN autre module du projet (il est importé par web,
scraper, analyze et core) : cela évite tout import circulaire.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Annonce:
    """Une annonce leboncoin telle qu'elle traverse le pipeline.

    Les champs du haut proviennent de la liste de résultats (web._ad_summary) ;
    `description` est complétée à l'étape de téléchargement ; `score`,
    `interessant`, `raison`, `erreur` sont renseignés par le jugement LLM.
    L'enregistrement persistant (seen.json) est un sous-ensemble produit par
    core._record — ce dataclass reste l'objet vivant du run."""

    id: object
    titre: str | None = None
    prix: object = None
    url: str | None = None
    ville: str | None = None
    date_publication: str | None = None
    categorie: str | None = None
    marque: str | None = None
    code_postal: str | None = None
    departement: str | None = None
    attributs: dict = field(default_factory=dict)
    nb_images: int = 0
    description: str | None = None
    # Renseignés par l'analyse (analyze._judge_description) :
    score: int = 0
    interessant: bool = False
    raison: str = ""
    erreur: bool = False

    @property
    def id_str(self) -> str:
        """Identifiant en chaîne — clé stable de seen.json et des dédoublonnages."""
        return str(self.id)


@dataclass
class Progress:
    """Événement de progression émis par scraper et analyze, relayé à l'UI.

    `item` n'est renseigné que lorsqu'une annonce vient d'être jugée (phase
    « analyse ») : core s'en sert pour persister l'annonce dans seen.json de façon
    incrémentale. L'interface n'utilise que phase/current/total/message."""

    phase: str  # "scraping" | "analyse"
    current: int
    total: int
    message: str
    item: Annonce | None = None
