# Contribuer à lebonparser

Merci de l'intérêt que tu portes au projet ! Les contributions sont les bienvenues :
corrections de bugs, améliorations, documentation, idées.

En participant, tu acceptes le [Code de Conduite](CODE_OF_CONDUCT.md) et
l'[avertissement légal](DISCLAIMER.md).

## Mettre en place l'environnement

Le projet utilise un environnement virtuel Python (dossier `.venv`).

```powershell
# Dépendances de l'application
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# (optionnel) Dépendances de la documentation
.\.venv\Scripts\python.exe -m pip install -r requirements-docs.txt
```

Prérequis fonctionnels : **Firefox** connecté à leboncoin (cookie `datadome`) et
**[Ollama](https://ollama.com/download)** avec le modèle `qwen3:8b`
(`ollama pull qwen3:8b`). Voir la [documentation](docs/utilisation.md).

Lancer l'application :

```powershell
.\.venv\Scripts\python.exe app.py    # http://127.0.0.1:5000
```

## Signaler un bug / proposer une idée

Ouvre une **issue** en utilisant le gabarit adapté (bug ou suggestion). Décris le
contexte, les étapes pour reproduire, et ce que tu attendais. **N'inclus jamais de
données personnelles** (annonces réelles, cookies, captures contenant des coordonnées).

## Proposer une modification (Pull Request)

1. **Forke** le dépôt et crée une branche depuis `main` (`fix/...` ou `feat/...`).
2. Fais des commits clairs et ciblés.
3. Vérifie que l'app démarre et que la doc se construit :
   ```powershell
   .\.venv\Scripts\python.exe -c "import app"        # imports OK
   .\.venv\Scripts\python.exe -m mkdocs build --strict
   ```
4. Ouvre la Pull Request en remplissant le gabarit.

## Style de code

- **Python** : suis le style du code existant (PEP 8, lignes ~95 colonnes).
- **Commentaires et docstrings en français**, comme le reste du projet ; explique le
  *pourquoi* plutôt que le *quoi*.
- Garde les modules à **responsabilité unique** : `web.py` (accès site), `scraper.py`
  (liste), `analyze.py`/`llm.py` (jugement), `core.py` (orchestration), `app.py` (web).
- Pas encore de suite de tests automatisés : les contributions ajoutant des **tests**
  (ex. `pytest` sur `core`/`analyze` avec `web`/`llm` simulés) sont particulièrement
  appréciées.

## Ce qui ne doit JAMAIS être commité

`data/`, `searches/`, `runs/`, `.venv/`, `site/` (déjà dans `.gitignore`) — ils
contiennent des données scrapées (tiers) ou de l'état local. Vérifie ton
`git status` avant de pousser.
