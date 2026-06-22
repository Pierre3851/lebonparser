# Utilisation

## Prérequis

| Composant | Détail |
|---|---|
| **Firefox** | connecté à ton compte leboncoin, ayant ouvert le site récemment (cookie `datadome` valide). |
| **Python** | un environnement virtuel est fourni dans `.venv`. |
| **[Ollama](https://ollama.com/download)** | installé et lancé, avec le modèle tiré : `ollama pull qwen3:8b`. |

## Installation

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Lancer l'application

```powershell
.\.venv\Scripts\python.exe app.py
```

Le navigateur s'ouvre automatiquement sur <http://127.0.0.1:5000>. L'app est **locale
et mono-utilisateur** : elle n'écoute que `127.0.0.1` (rien n'est exposé sur le réseau).

!!! note "Pourquoi Firefox doit rester connecté"
    leboncoin est protégé par **DataDome** (anti-bot). lebonparser réutilise les
    cookies de ta session Firefox (dont le cookie `datadome`) pour passer pour un
    vrai navigateur. Si le scraping échoue, recharge une page leboncoin dans Firefox
    puis relance.

## 1. Créer une recherche

Sur la page d'accueil, remplis le formulaire :

- **Nom** : libellé libre (ex. *combinaison néoprène homme*).
- **URL(s)** : colle l'URL d'une recherche leboncoin (avec tous ses filtres). Le
  bouton **« + Ajouter une URL »** permet d'en ajouter d'autres — une recherche
  couvre souvent plusieurs sections du site, elles seront fusionnées et
  dédoublonnées.
- **Critère** : décris en français ce qui rend une annonce intéressante. Sois
  précis et indique aussi ce qui **ne** t'intéresse **pas**.

!!! tip "Rédiger un bon critère"
    Le bas de la page d'accueil contient une section **« Création du critère »** :
    un méta-prompt prêt à copier-coller dans un chatbot grand public (Gemini,
    ChatGPT…). Tu le complètes avec ton besoin, le chatbot (qui peut chercher sur
    internet le vocabulaire/les specs du produit) t'aide à rédiger un critère
    complet et strict, que tu n'as plus qu'à recoller dans le champ.

## 2. Lancer un run

Clique **Run** sur la ligne de la recherche. Une barre de progression suit en direct :

- **scraping** — `Source i/N — page x/y — n annonces`
- **analyse** — `Analyse i/total — <titre>` (seulement les nouvelles annonces)

Le 1er run analyse toutes les annonces (plusieurs minutes selon le volume). **Les
runs suivants ne jugent que les nouveautés** : relancer juste après donne « 0
nouvelle » en quelques secondes — c'est la preuve que l'incrémental fonctionne. Au
quotidien, un clic suffit.

## 3. Lire les résultats

Le bouton **Résultats** ouvre la page de la recherche :

- **Nouveautés du dernier run** mises en avant ;
- **Historique complet** des annonces retenues (score ≥ `SCORE_MIN`), trié par score ;
- chaque carte affiche titre, prix, ville, score, justification du LLM, description ;
- le bouton **« Tout ouvrir »** en haut de page ouvre toutes les annonces validées
  dans des onglets (autorise les pop-ups pour le site si le navigateur les bloque).

## Réglages globaux (`config.py`)

Le formulaire gère le par-recherche (URL, critère) ; `config.py` règle le **global** :

| Réglage | Rôle | Défaut |
|---|---|---|
| `OLLAMA_MODEL` | modèle Ollama utilisé | `qwen3:8b` |
| `OLLAMA_THINK` | mode raisonnement de qwen3 | `True` |
| `OLLAMA_NUM_CTX` | taille du contexte (tokens) | `8192` |
| `OLLAMA_NUM_PREDICT` | tokens générés max (raisonnement + JSON) | `4096` |
| `SCORE_MIN` | score minimal pour retenir une annonce | `6` |
| `DELAY_BETWEEN_PAGES` | délai aléatoire (s) anti-DataDome | `(2.0, 5.0)` |
| `MIN_FETCH_INTERVAL` | intervalle plancher entre 2 requêtes (s) | `1.5` |
| `BROWSER` | navigateur source des cookies | `firefox` |

## Suivi des tokens

À chaque jugement, le journal indique les tokens consommés
(`prompt + génération = total / num_ctx`). Un **avertissement** s'affiche dès que le
total dépasse **75 % de `num_ctx`** (marge de contexte faible), et une alerte plus
forte si le prompt est plafonné à `num_ctx` (contexte trop petit → augmente
`OLLAMA_NUM_CTX`).

## En cas de blocage DataDome

- Recharge **leboncoin.fr dans Firefox** (connecté) pour rafraîchir le cookie.
- Augmente `DELAY_BETWEEN_PAGES` / `MIN_FETCH_INTERVAL`.
- Le journal de chaque run est dans `searches/<slug>/analyse.log`.
