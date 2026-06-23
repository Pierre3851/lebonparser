"""Réglages GLOBAUX de lebonparser (valables pour toutes les recherches).

Le par-recherche (nom, URL, critère) est saisi dans l'interface web et stocké
dans searches/<slug>/search.json — il n'a pas sa place ici. Ce fichier ne contient
que les réglages transverses : accès au site, paramètres du LLM, seuils, délais.

Les secrets (clé d'API du LLM distant) ne sont PAS ici : ils sont lus depuis un
fichier .env (non commité) chargé ci-dessous. Voir .env.example pour le modèle.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Charge .env (placé à la racine du projet, à côté de ce fichier) dans l'environnement.
# Ne fait rien si le fichier est absent (le backend "ollama" n'en a pas besoin).
load_dotenv(Path(__file__).with_name(".env"))

# ---------------------------------------------------------------------------
# Accès au site / scraping
# ---------------------------------------------------------------------------

# Nombre d'annonces par page (35 = valeur standard leboncoin).
PAGE_SIZE = 35

# Délai aléatoire (secondes) entre deux pages, pour rester discret face à DataDome.
DELAY_BETWEEN_PAGES = (2.0, 5.0)  # (min, max)

# Sécurité : nombre maximum de pages à récupérer par URL (garde-fou).
MAX_PAGES = 50

# DataDome protège leboncoin. On réutilise la session d'un vrai navigateur
# connecté : ses cookies (dont datadome) sont extraits automatiquement.
BROWSER = "firefox"  # firefox | chrome | edge | brave ...
# User-Agent desktop cohérent avec le navigateur d'où vient le cookie datadome.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0"
)
HTTP_TIMEOUT = 30.0

# ---------------------------------------------------------------------------
# Choix du backend LLM
# ---------------------------------------------------------------------------
# "ollama" : modèle local (GPU recommandé) — réglages OLLAMA_* ci-dessous.
# "api"    : LLM distant via clé d'API (aucun GPU requis, jugement parallélisable)
#            — config dans .env (voir .env.example). L'application est AGNOSTIQUE
#            du fournisseur : tout le spécifique (fournisseur, modèle, clé) vit
#            dans .env via Instructor, jamais dans le code.


def _require_env(name: str) -> str:
    """Lit une variable .env OBLIGATOIRE. AUCUNE valeur par défaut : si elle manque,
    on lève une erreur explicite affichée à l'utilisateur, plutôt que de retomber sur
    un comportement implicite (pas de défaut, pas de fallback silencieux)."""
    val = (os.environ.get(name) or "").strip()
    if not val:
        raise SystemExit(
            f"Variable « {name} » absente du fichier .env (aucune valeur par défaut "
            f"n'est utilisée). Renseigne-la — voir .env.example."
        )
    return val


# Config LLM, peuplée par validate() au démarrage (cf. app.main). Tant que validate()
# n'a pas été appelée, ces variables valent None : importer ce module ne valide donc
# rien et n'exige pas de .env — pratique pour les tests et les imports utilitaires.
# La validation reste fail-fast, mais explicitement déclenchée au point d'entrée.
LLM_BACKEND = None
LLM_MODEL = None
LLM_MAX_TOKENS = None
LLM_CONCURRENCY = None
LLM_RPM = None


def validate() -> None:
    """Valide la config LLM (.env) et peuple les variables de module ci-dessus.

    À appeler une fois au démarrage de l'application. Lève SystemExit avec un message
    clair si une variable obligatoire manque ou est invalide (aucun défaut, aucun
    fallback). Les variables « api » ne sont exigées que si LLM_BACKEND == "api"."""
    global LLM_BACKEND, LLM_MODEL, LLM_MAX_TOKENS, LLM_CONCURRENCY, LLM_RPM
    LLM_BACKEND = _require_env("LLM_BACKEND")
    if LLM_BACKEND not in ("ollama", "api"):
        raise SystemExit(
            f"LLM_BACKEND doit valoir « ollama » ou « api » (lu : « {LLM_BACKEND} »)."
        )
    if LLM_BACKEND == "api":
        LLM_MODEL = _require_env("LLM_MODEL")
        LLM_MAX_TOKENS = int(_require_env("LLM_MAX_TOKENS"))
        LLM_CONCURRENCY = int(_require_env("LLM_CONCURRENCY"))
        LLM_RPM = int(_require_env("LLM_RPM"))
        if LLM_RPM <= 0:
            raise SystemExit("LLM_RPM doit être un entier > 0 (requêtes/minute).")
        _require_env("LLM_API_KEY")  # secret lu au moment de construire le client (llm.py)

# ---------------------------------------------------------------------------
# Analyse par le LLM local (Ollama)  — backend "ollama"
# ---------------------------------------------------------------------------

OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "qwen3:8b"

# Paramètres d'inférence (cf. docs Ollama 2026 : capabilities/thinking, modelfile).
#  - THINK : mode raisonnement de qwen3. False = réponse directe (True/False ; les
#    niveaux "low/medium/high" sont réservés à GPT-OSS.)
OLLAMA_THINK = True
#  - TEMPERATURE : 0 = déterministe (recommandé pour un classement reproductible).
OLLAMA_TEMPERATURE = 0.0
#  - NUM_CTX : taille du contexte. En mode thinking le raisonnement s'ajoute au
#    prompt+réponse, donc on prévoit large (8192) ; sinon 4096 suffirait.
OLLAMA_NUM_CTX = 8192
#  - NUM_PREDICT : nombre max de tokens GÉNÉRÉS (raisonnement + réponse JSON).
#    ATTENTION avec le thinking : le raisonnement consomme ce budget AVANT le JSON ;
#    une valeur trop basse tronque la réponse → content vide (done_reason="length").
#    On prévoit large (4096), MAIS le raisonnement de qwen3 peut être quasi sans fin :
#    llm.judge rejuge donc l'annonce sans thinking si le budget est épuisé (filet de
#    sécurité fiable, cf. llm.py).
OLLAMA_NUM_PREDICT = 4096

# ---------------------------------------------------------------------------
# Analyse par un LLM distant via clé d'API  — backend "api"
# ---------------------------------------------------------------------------
# Backend "api" : TOUT vient de .env, AUCUN défaut, validé par validate() (ci-dessus).
# Ces variables ne sont exigées que si LLM_BACKEND == "api" (un utilisateur Ollama n'a
# pas à les renseigner) :
#   - LLM_MODEL      : modèle au format Instructor "<fournisseur>/<modèle>". C'est le
#                      SEUL endroit qui désigne le fournisseur ; le code l'ignore.
#   - LLM_MAX_TOKENS : plafond de tokens générés par jugement (réponse JSON courte).
#   - LLM_CONCURRENCY: jugements menés EN PARALLÈLE. ⚠ Seul l'appel au LLM distant
#                      est parallélisé ; le téléchargement des annonces reste SÉQUENTIEL
#                      et throttlé (anti-DataDome).
#   - LLM_RPM        : débit MAX en requêtes/minute autorisé par ton offre. L'app
#                      espace les départs (60/LLM_RPM s) pour ne jamais le dépasser
#                      → aucun 429 (ex. palier gratuit Gemini = 15).
#   - LLM_API_KEY    : clé du fournisseur (présence vérifiée par validate(), lue par llm.py).

# On retient les annonces dont le score (0-10) attribué par le LLM est >= :
SCORE_MIN = 6

# La latence du LLM espace déjà les requêtes. Ce plancher garantit malgré tout un
# intervalle minimal (s) entre deux téléchargements, au cas où l'inférence soit
# très rapide — pour ne pas déclencher DataDome.
MIN_FETCH_INTERVAL = 1.5
