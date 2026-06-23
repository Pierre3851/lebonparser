"""Interface avec le LLM, en sortie structurée (JSON), pour juger une annonce.

Deux backends, choisis par `config.LLM_BACKEND` :
  - "ollama" : modèle local (GPU recommandé), via le client Ollama, en mode
    thinking avec un filet anti-troncature ;
  - "api"    : LLM distant via clé d'API (aucun GPU requis), via Instructor —
    une seule interface pour Anthropic/OpenAI/… avec validation Pydantic et
    retries automatiques sur erreur de schéma.

Dans les deux cas on demande au modèle de juger une annonce vis-à-vis d'un
critère en langage naturel, et on récupère un objet validé
{interessant, score, raison}.
"""

from __future__ import annotations

import logging
import threading
import time

from pydantic import BaseModel, Field

import config

log = logging.getLogger("lebonparser")


class Jugement(BaseModel):
    interessant: bool = Field(description="L'annonce correspond-elle au critère ?")
    score: int = Field(ge=0, le=10, description="Pertinence de 0 (hors sujet) à 10 (parfait)")
    raison: str = Field(description="Justification courte (1 phrase)")


_SYSTEM = (
    "Tu tries des annonces leboncoin selon le critère de l'utilisateur, en jugeant "
    "uniquement le contenu de l'annonce, sans rien inventer. Les annonces leboncoin "
    "ont souvent une description courte et incomplète : ne confonds pas une info "
    "absente avec une contradiction, et dans le doute reste permissif (garde "
    "l'annonce). Trois cas :\n"
    "- l'annonce correspond au critère → score élevé (garder) ;\n"
    "- l'annonce contredit le critère (mauvais type, caractéristique hors cible, "
    "abîmé) → score bas (écarter) ;\n"
    "- infos insuffisantes pour trancher → score moyen (5-6, garder pour "
    "vérification manuelle).\n"
    "Réponds exclusivement en JSON."
)


def _user(annonce_texte: str, critere: str) -> str:
    return (
        f"CRITÈRE RECHERCHÉ :\n{critere.strip()}\n\n"
        f"ANNONCE À ÉVALUER :\n{annonce_texte.strip()}\n\n"
        "Évalue la correspondance et réponds en JSON "
        "(champs: interessant, score 0-10, raison)."
    )


def judge(annonce_texte: str, critere: str) -> tuple[Jugement, str]:
    """Juge une annonce selon `critere`. Renvoie (Jugement validé, trace de raisonnement).

    La trace est vide hors mode thinking Ollama (notamment pour le backend API)."""
    if config.LLM_BACKEND == "api":
        return _judge_api(annonce_texte, critere)
    return _judge_ollama(annonce_texte, critere)


def check_ready() -> None:
    """Vérifie que le backend choisi est utilisable (sinon explique)."""
    if config.LLM_BACKEND == "api":
        _check_ready_api()
    else:
        _check_ready_ollama()


# --------------------------------------------------------------------------- #
# Backend "ollama" (modèle local)
# --------------------------------------------------------------------------- #

_ollama_client = None
_ollama_lock = threading.Lock()


def _client():
    """Client Ollama (créé à la demande)."""
    global _ollama_client
    if _ollama_client is None:
        with _ollama_lock:
            if _ollama_client is None:
                import ollama
                _ollama_client = ollama.Client(host=config.OLLAMA_HOST)
    return _ollama_client


def _judge_ollama(annonce_texte: str, critere: str) -> tuple[Jugement, str]:
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _user(annonce_texte, critere)},
    ]
    kwargs = dict(
        model=config.OLLAMA_MODEL,
        messages=messages,
        format=Jugement.model_json_schema(),  # sortie JSON structurée
        options={
            "temperature": config.OLLAMA_TEMPERATURE,
            "num_ctx": config.OLLAMA_NUM_CTX,
            "num_predict": config.OLLAMA_NUM_PREDICT,
        },
    )

    def _chat(think):
        # Pas de repli sur une ancienne signature : si le client ollama ne supporte
        # pas `think`, l'erreur doit remonter (aucun fallback silencieux).
        return _client().chat(think=think, **kwargs)

    resp = _chat(config.OLLAMA_THINK)
    content = (resp["message"].get("content") or "").strip()
    thinking = (resp["message"].get("thinking") or "").strip()

    # qwen3 en mode thinking : le raisonnement peut épuiser tout le budget num_predict
    # (parfois des milliers de tokens) sans jamais écrire le JSON → content vide,
    # done_reason="length". Augmenter num_predict ne garantit rien (le raisonnement
    # peut rester sans fin). On rejuge alors l'annonce SANS thinking : réponse directe,
    # le JSON est produit immédiatement — mieux vaut un verdict que perdre l'annonce.
    if not content and resp.get("done_reason") == "length" and config.OLLAMA_THINK:
        resp = _chat(False)
        retry = (resp["message"].get("content") or "").strip()
        if retry:
            note = "[raisonnement tronqué (budget num_predict atteint) → rejugé sans thinking]"
            thinking = f"{thinking}\n{note}".strip() if thinking else note
            content = retry

    _log_usage_ollama(resp)

    if not content:
        raise ValueError(
            f"Réponse vide (done_reason={resp.get('done_reason')}). "
            "Augmente OLLAMA_NUM_PREDICT / OLLAMA_NUM_CTX (raisonnement trop long)."
        )
    return Jugement.model_validate_json(content), thinking


def _log_usage_ollama(resp) -> None:
    """Journalise l'usage en tokens d'une réponse Ollama, pour valider le contexte.

    Champs Ollama (doc : https://docs.ollama.com/api) :
      - prompt_eval_count : tokens du prompt (entrée) ;
      - eval_count        : tokens générés (raisonnement + réponse).
    Le total occupé dans la fenêtre = somme des deux ; on le compare à num_ctx.
    Alerte si le prompt est plafonné à num_ctx (signe que le contexte est trop petit)
    ou si le total dépasse 75 % de num_ctx."""
    prompt = resp.get("prompt_eval_count") or 0
    genere = resp.get("eval_count") or 0
    total = prompt + genere
    ctx = config.OLLAMA_NUM_CTX
    log.info(
        "        tokens : prompt=%d + génération=%d = %d / num_ctx=%d (%d%%)",
        prompt, genere, total, ctx, round(100 * total / ctx) if ctx else 0,
    )
    if ctx and prompt >= ctx:
        log.warning("        ⚠ prompt plafonné à num_ctx (%d) : contexte trop petit, "
                    "augmente OLLAMA_NUM_CTX.", ctx)
    elif ctx and total >= 0.75 * ctx:
        log.warning("        ⚠ %d/%d tokens (%d%% > 75%% de num_ctx) : marge de contexte "
                    "faible, envisage d'augmenter OLLAMA_NUM_CTX.",
                    total, ctx, round(100 * total / ctx))


def _check_ready_ollama() -> None:
    """Vérifie qu'Ollama répond et que le modèle est disponible (sinon explique)."""
    try:
        models = [m["model"] for m in _client().list().get("models", [])]
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"Ollama injoignable sur {config.OLLAMA_HOST} ({exc}).\n"
            "Installe-le (https://ollama.com/download), puis lance-le."
        )
    if not any(m == config.OLLAMA_MODEL or m.startswith(config.OLLAMA_MODEL + ":")
               for m in models):
        raise SystemExit(
            f"Modèle '{config.OLLAMA_MODEL}' absent. Lance : "
            f"ollama pull {config.OLLAMA_MODEL}\nModèles présents : {models}"
        )


# --------------------------------------------------------------------------- #
# Backend "api" (LLM distant via Instructor)
# --------------------------------------------------------------------------- #

# Variable d'environnement (chargée depuis .env par config) contenant la clé d'API.
_API_KEY_ENV = "LLM_API_KEY"

_api_client_singleton = None
_api_lock = threading.Lock()


class _RateLimiter:
    """Limiteur de débit thread-safe : garantit au plus `rpm` départs de requêtes
    par minute, en RÉSERVANT à chaque appel un créneau espacé de 60/rpm secondes.

    Chaque thread réserve son créneau sous verrou (donc des créneaux distincts et
    régulièrement espacés), puis attend l'heure réservée HORS verrou — les attentes
    se chevauchent, ce qui reste compatible avec le ThreadPool de jugement.
    On ne dépasse donc jamais la limite du fournisseur : aucun 429 (prévention, pas
    de retry ni de fallback)."""

    def __init__(self, rpm: int):
        self._interval = 60.0 / rpm
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_allowed)
            self._next_allowed = start + self._interval
            wait = start - now
        if wait > 0:
            log.debug("        débit : attente %.1fs (LLM_RPM=%d)", wait, config.LLM_RPM)
            time.sleep(wait)


_rate_limiter_singleton = None


def _rate_limiter() -> _RateLimiter:
    """Limiteur de débit partagé (créé à la demande, après lecture de config.LLM_RPM)."""
    global _rate_limiter_singleton
    if _rate_limiter_singleton is None:
        with _api_lock:
            if _rate_limiter_singleton is None:
                _rate_limiter_singleton = _RateLimiter(config.LLM_RPM)
    return _rate_limiter_singleton


def _api_client():
    """Client Instructor (créé à la demande, partagé entre threads).

    La clé est transmise explicitement (depuis LLM_API_KEY) plutôt que via la
    variable propre au fournisseur, pour rester indépendant du fournisseur.
    Le client sous-jacent (httpx) gère les requêtes concurrentes — on peut donc
    le réutiliser depuis le ThreadPool de jugement (cf. analyze._analyser_parallele)."""
    global _api_client_singleton
    if _api_client_singleton is None:
        with _api_lock:
            if _api_client_singleton is None:
                import instructor
                # Pas de `mode=` : Instructor choisit le mode adapté au fournisseur
                # (sortie structurée / tools selon Anthropic, Gemini, OpenAI…).
                # Clé lue via _require_env : erreur explicite si absente (jamais None).
                _api_client_singleton = instructor.from_provider(
                    config.API_MODEL,
                    api_key=config._require_env(_API_KEY_ENV),
                )
    return _api_client_singleton


def _judge_api(annonce_texte: str, critere: str) -> tuple[Jugement, str]:
    # Instructor valide la réponse contre Jugement et relance jusqu'à 2 fois si le
    # schéma n'est pas respecté (remplace le filet anti-troncature d'Ollama).
    # Respecte le débit max du fournisseur (LLM_RPM) AVANT d'émettre la requête :
    # espace les départs pour ne jamais déclencher de 429 (prévention déterministe).
    _rate_limiter().acquire()
    # Pas de comptage de tokens ici : il n'existe pas de champ d'usage agnostique
    # entre fournisseurs sans ajouter une dépendance (LiteLLM). On évite donc toute
    # lecture tolérante multi-champs ; suivi du coût via le tableau de bord du fournisseur.
    jugement = _api_client().chat.completions.create(
        response_model=Jugement,
        max_retries=2,
        max_tokens=config.API_MAX_TOKENS,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _user(annonce_texte, critere)},
        ],
    )
    return jugement, ""  # pas de trace de raisonnement en mode API


def _check_ready_api() -> None:
    """Vérifie que le client API est initialisable.

    La présence des variables .env requises (dont LLM_API_KEY) est déjà exigée par
    config au démarrage — sans valeur par défaut. Ici on ne fait que construire le
    client, pour détecter tôt un modèle/paquet fournisseur invalide."""
    try:
        _api_client()
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"Client API '{config.API_MODEL}' non initialisable ({exc}).\n"
            "Vérifie le nom du modèle (format Instructor « fournisseur/modèle ») "
            "et que le paquet du fournisseur est installé."
        )
