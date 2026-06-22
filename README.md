# lebonparser

![Licence](https://img.shields.io/badge/licence-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)
![LLM local](https://img.shields.io/badge/LLM-Ollama%20%C2%B7%20local-22a06b.svg)

Récupère **toutes** les annonces d'une (ou plusieurs) recherche leboncoin, puis les
filtre avec un **LLM local** (via Ollama) pour ne garder que celles qui correspondent
à un critère décrit en langage naturel. Le tout 100 % sur ta machine, sans envoyer
tes données à un service tiers.

> 📖 **Documentation complète** (objectif, utilisation, architecture & diagrammes) :
> voir le dossier [`docs/`](docs/index.md), publié sur **GitHub Pages**.

> ⚖️ **Usage personnel et éducatif.** Le scraping peut être contraire aux CGU de
> leboncoin et les annonces contiennent des données de tiers — lis l'[avertissement
> légal](DISCLAIMER.md) avant toute utilisation.

## Comment ça marche

leboncoin est protégé par **DataDome** (anti-bot). La méthode retenue réutilise
la session de ton navigateur **Firefox connecté** : ses cookies (dont le cookie
`datadome`, validé côté serveur) sont injectés dans des requêtes imitant Firefox
(`curl_cffi`). Les données sont lues dans le JSON `__NEXT_DATA__` des pages.

Pour chaque annonce : téléchargement du texte intégral, puis jugement par le LLM
local (sortie structurée `{interessant, score, raison}`). On retient celles dont le
score (0-10) dépasse `SCORE_MIN`.

## Utilisation

Une petite app **Flask locale** : on y enregistre des recherches (nom + liste d'URL +
critère) et un bouton **Run** ne ré-analyse que les **nouvelles** annonces — idéal
pour un suivi quotidien en un clic. La mémoire des annonces déjà vues
(`searches/<slug>/seen.json`) rend les runs incrémentaux.

```powershell
.\.venv\Scripts\python.exe app.py      # ouvre http://127.0.0.1:5000
```

Crée ensuite une recherche dans le navigateur (nom, une ou plusieurs URL leboncoin,
critère en langage naturel), puis clique **Run**. Voir la
[documentation](docs/utilisation.md) pour le détail.

## Prérequis

- **Firefox**, connecté à ton compte leboncoin, ayant ouvert le site au moins une
  fois récemment (pour disposer d'un cookie `datadome` valide).
- **Python** (venv déjà fourni dans `.venv`).
- **[Ollama](https://ollama.com/download)** installé, puis le modèle :
  ```
  ollama pull qwen3:8b
  ```

## Installation

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Fichiers

| Fichier | Rôle |
|---|---|
| `app.py` | interface web Flask (multi-recherches, runs incrémentaux) |
| `core.py` | cœur : stockage des recherches (`searches/`) + `run_search()` |
| `config.py` | réglages globaux (modèle, seuils, délais) |
| `cookies.py` | extraction des cookies leboncoin depuis le navigateur |
| `web.py` | session HTTP + parsing `__NEXT_DATA__` (liste & détail) |
| `scraper.py` | récupère la liste des annonces (`scrape()`) |
| `llm.py` | appel Ollama en sortie structurée (`interessant`/`score`/`raison`) |
| `analyze.py` | texte intégral + jugement LLM, en flux (`analyser_liste()`) |
| `templates/` | pages de l'app web (`index.html`, `results.html`) |
| `docs/` | documentation MkDocs (GitHub Pages) |

## Documentation

La doc est construite avec **MkDocs Material** (diagrammes **PlantUML**) :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-docs.txt
.\.venv\Scripts\python.exe -m mkdocs serve     # aperçu local sur http://127.0.0.1:8000
```

Le push sur `main` publie automatiquement la doc sur GitHub Pages
(voir [`.github/workflows/docs.yml`](.github/workflows/docs.yml)).

## En cas de blocage DataDome

- Ouvre/recharge **leboncoin.fr dans Firefox** (connecté) pour rafraîchir le cookie.
- Augmente `DELAY_BETWEEN_PAGES` / `MIN_FETCH_INTERVAL` dans `config.py`.
- En dernier recours : navigateur furtif **Camoufox** (non implémenté ici).

## Contribuer

Les contributions sont les bienvenues ! Lis le [guide de contribution](CONTRIBUTING.md)
et le [code de conduite](CODE_OF_CONDUCT.md). Pour signaler une faille, voir la
[politique de sécurité](SECURITY.md).

## Licence

Distribué sous licence [MIT](LICENSE) — © 2026 Pixerot.
