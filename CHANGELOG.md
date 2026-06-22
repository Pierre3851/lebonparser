# Changelog

Toutes les évolutions notables de ce projet sont documentées ici.

Le format s'inspire de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/)
et le projet suit le [versionnage sémantique](https://semver.org/lang/fr/).

## [Non publié]

### Ajouté
- Interface web locale (Flask) : gestion de plusieurs recherches, runs incrémentaux
  ne jugeant que les nouvelles annonces, suivi de progression en direct.
- Mémoire par recherche (`searches/<slug>/seen.json`) évitant de rejuger l'existant.
- Documentation MkDocs (objectif, utilisation, architecture) avec diagrammes PlantUML,
  publiée sur GitHub Pages.
- Fichiers communautaires : licence MIT, code de conduite, guide de contribution,
  politique de sécurité, avertissement légal, gabarits d'issues et de PR.
- Journalisation des tokens par requête + avertissement au-delà de 75 % de `num_ctx`.

### Modifié
- Projet recentré sur l'**application web** : suppression de l'ancien pipeline en
  ligne de commande (`report.py`, points d'entrée CLI de `scraper.py`/`analyze.py`).

[Non publié]: https://github.com/Pixerot/lebonparser
