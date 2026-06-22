"""Interface avec le LLM local via Ollama, en sortie structurée (JSON).

On demande au modèle de juger une annonce vis-à-vis d'un critère en langage
naturel (propre à chaque recherche), et on récupère un objet validé
{interessant, score, raison}.
"""

from __future__ import annotations

import logging

import ollama
from pydantic import BaseModel, Field

import config

log = logging.getLogger("lebonparser")


class Jugement(BaseModel):
    interessant: bool = Field(description="L'annonce correspond-elle au critère ?")
    score: int = Field(ge=0, le=10, description="Pertinence de 0 (hors sujet) à 10 (parfait)")
    raison: str = Field(description="Justification courte (1 phrase)")


_client = ollama.Client(host=config.OLLAMA_HOST)

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


def judge(annonce_texte: str, critere: str) -> tuple[Jugement, str]:
    """Juge une annonce selon `critere`. Renvoie (Jugement validé, trace de raisonnement).

    La trace (`message.thinking`) est vide si le mode thinking est désactivé."""
    user = (
        f"CRITÈRE RECHERCHÉ :\n{critere.strip()}\n\n"
        f"ANNONCE À ÉVALUER :\n{annonce_texte.strip()}\n\n"
        "Évalue la correspondance et réponds en JSON "
        "(champs: interessant, score 0-10, raison)."
    )
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
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
        try:
            return _client.chat(think=think, **kwargs)
        except TypeError:
            return _client.chat(**kwargs)  # ancienne version d'ollama sans 'think'

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

    _log_usage(resp)

    if not content:
        raise ValueError(
            f"Réponse vide (done_reason={resp.get('done_reason')}). "
            "Augmente OLLAMA_NUM_PREDICT / OLLAMA_NUM_CTX (raisonnement trop long)."
        )
    return Jugement.model_validate_json(content), thinking


def _log_usage(resp) -> None:
    """Journalise l'usage en tokens d'une réponse, pour valider la taille du contexte.

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


def check_ready() -> None:
    """Vérifie qu'Ollama répond et que le modèle est disponible (sinon explique)."""
    try:
        models = [m["model"] for m in _client.list().get("models", [])]
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
