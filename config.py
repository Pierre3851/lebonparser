"""Réglages GLOBAUX de lebonparser (valables pour toutes les recherches).

Le par-recherche (nom, URL, critère) est saisi dans l'interface web et stocké
dans searches/<slug>/search.json — il n'a pas sa place ici. Ce fichier ne contient
que les réglages transverses : accès au site, paramètres du LLM, seuils, délais.
"""

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
# Analyse par le LLM local (Ollama)
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

# On retient les annonces dont le score (0-10) attribué par le LLM est >= :
SCORE_MIN = 6

# La latence du LLM espace déjà les requêtes. Ce plancher garantit malgré tout un
# intervalle minimal (s) entre deux téléchargements, au cas où l'inférence soit
# très rapide — pour ne pas déclencher DataDome.
MIN_FETCH_INTERVAL = 1.5
