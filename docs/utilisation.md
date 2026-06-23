# Utilisation

## Prérequis

| Composant | Détail |
|---|---|
| **Firefox** | connecté à ton compte leboncoin, ayant ouvert le site récemment (cookie `datadome` valide). |
| **Python** | un environnement virtuel est fourni dans `.venv`. |
| **LLM** | au choix : **Ollama** local *ou* une **clé d'API** distante — voir [Choisir le backend LLM](#choisir-le-backend-llm). |

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

## Choisir le backend LLM

lebonparser peut faire juger les annonces par un **modèle local (Ollama)** ou par un
**LLM distant via clé d'API**. Le choix se fait dans `.env` (`LLM_BACKEND`), qui est
**obligatoire** — il n'y a aucune valeur par défaut.

=== "Ollama (local)"

    Aucune clé, aucun coût, données qui ne quittent pas la machine — mais un **GPU est
    recommandé** (sinon c'est lent). Installe [Ollama](https://ollama.com/download),
    lance-le, et tire le modèle :

    ```powershell
    ollama pull qwen3:8b
    ```

    Dans `.env` : `LLM_BACKEND=ollama` (les réglages du modèle local restent dans
    `config.py`, section `OLLAMA_*`).

=== "API distante (sans GPU)"

    Pour une machine **sans GPU**, et pour des runs **plus rapides** (les jugements
    sont menés **en parallèle**). Copie `.env.example` en **`.env`** (jamais commité,
    ignoré par git) et renseigne **toutes** les variables — il n'y a **aucune valeur
    par défaut** : une variable absente provoque une erreur explicite au démarrage.

    ```bash
    LLM_BACKEND=api
    LLM_MODEL=google/gemini-3.1-flash-lite   # « fournisseur/modèle » (⚠ Gemini = « google/ »)
    LLM_API_KEY=ta-cle
    LLM_MAX_TOKENS=1024
    LLM_CONCURRENCY=6
    LLM_RPM=15                               # débit max req/min de ton offre (gratuit Gemini = 15)
    ```

    Le fichier `.env` est chargé automatiquement au démarrage (via `python-dotenv`).

    !!! warning "Téléchargement séquentiel · débit LLM plafonné"
        Seul **l'appel au LLM** est parallélisé (`LLM_CONCURRENCY`). Le téléchargement
        des annonces sur leboncoin reste **séquentiel et throttlé** pour ne pas
        déclencher DataDome. Par ailleurs, le débit des appels LLM est **plafonné à
        `LLM_RPM`** (départs espacés de `60/LLM_RPM` s) : le débit effectif est donc
        borné par `LLM_RPM`, quelle que soit `LLM_CONCURRENCY` — c'est ce qui évite
        tout `429`.

    !!! tip "Coût"
        Claude Haiku 4.5 est très bon marché pour de la classification : ~**1 €** pour
        un premier run complet (quelques centaines d'annonces), puis **quasi gratuit**
        en quotidien incrémental (seules les nouveautés sont jugées).

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

!!! note "Backend API : deux phases"
    En backend `api`, l'analyse se fait en deux temps — d'abord le téléchargement des
    descriptions (séquentiel), puis le jugement **parallèle**. La barre avance pendant la
    phase de jugement ; le détail des deux phases est visible dans `analyse.log`.

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

## Réglages

Le formulaire gère le par-recherche (URL, critère). La config se répartit en deux
endroits : le **choix et les secrets du LLM** dans `.env`, le **reste** dans `config.py`.

### Dans `.env` (LLM) — aucune valeur par défaut

Ces variables sont **obligatoires** dès que `LLM_BACKEND=api` ; aucune n'a de valeur par
défaut — une variable absente provoque une **erreur explicite au démarrage**.

| Variable `.env` | Rôle |
|---|---|
| `LLM_BACKEND` | backend LLM : `ollama` (local) ou `api` (distant) — **toujours requis** |
| `LLM_MODEL` | modèle distant `« fournisseur/modèle »` (ex. `google/gemini-3.1-flash-lite`) |
| `LLM_API_KEY` | clé d'API du fournisseur (jamais dans le code, non commitée) |
| `LLM_MAX_TOKENS` | tokens générés max par jugement |
| `LLM_CONCURRENCY` | jugements menés en parallèle |
| `LLM_RPM` | débit max (req/min) de ton offre — l'app s'y tient, donc aucun 429 |

### Dans `config.py` (le reste)

| Réglage | Rôle | Valeur |
|---|---|---|
| `OLLAMA_MODEL` | modèle Ollama utilisé *(backend ollama)* | `qwen3:8b` |
| `OLLAMA_THINK` | mode raisonnement de qwen3 *(backend ollama)* | `True` |
| `OLLAMA_NUM_CTX` | taille du contexte (tokens) *(backend ollama)* | `8192` |
| `OLLAMA_NUM_PREDICT` | tokens générés max (raisonnement + JSON) *(backend ollama)* | `4096` |
| `SCORE_MIN` | score minimal pour retenir une annonce | `6` |
| `DELAY_BETWEEN_PAGES` | délai aléatoire (s) anti-DataDome | `(2.0, 5.0)` |
| `MIN_FETCH_INTERVAL` | intervalle plancher entre 2 requêtes (s) | `1.5` |
| `BROWSER` | navigateur source des cookies | `firefox` |

## Suivi des tokens

En backend **Ollama**, chaque jugement journalise les tokens consommés
(`prompt + génération = total`), comparés à `num_ctx` : un **avertissement** s'affiche dès
**75 %** (marge faible), et une alerte plus forte si le prompt est plafonné à `num_ctx`
(contexte trop petit → augmente `OLLAMA_NUM_CTX`).

En backend **API**, les tokens ne sont **pas** journalisés : il n'existe pas de champ
d'usage agnostique entre fournisseurs sans ajouter une dépendance. Suis le coût via le
**tableau de bord de ton fournisseur**.

## En cas de blocage DataDome

- Recharge **leboncoin.fr dans Firefox** (connecté) pour rafraîchir le cookie.
- Augmente `DELAY_BETWEEN_PAGES` / `MIN_FETCH_INTERVAL`.
- Le journal de chaque run est dans `searches/<slug>/analyse.log`.
