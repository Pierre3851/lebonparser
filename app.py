"""Interface web locale de lebonparser.

Une petite app Flask mono-utilisateur : on enregistre des recherches (URL + nom +
critère) et on les lance en un clic. Chaque run ne ré-analyse que les NOUVELLES
annonces (cf. core.run_search) ; la progression est suivie en direct par polling JSON.

Lancement :
    ./.venv/Scripts/python.exe app.py
puis ouvre http://127.0.0.1:5000 (ouvert automatiquement).
"""

from __future__ import annotations

import threading
import uuid
import webbrowser

from flask import (Flask, abort, jsonify, redirect, render_template,
                   request, url_for)

import config
import core

app = Flask(__name__)

# État des runs en mémoire (mono-utilisateur). task_id -> dict de progression.
RUNS: dict[str, dict] = {}
# Un seul run actif par recherche : slug -> task_id.
ACTIVE: dict[str, str] = {}
_lock = threading.Lock()


def _worker(task_id: str, slug: str) -> None:
    """Exécute la recherche dans un thread et publie l'avancement dans RUNS."""
    def cb(state: dict) -> None:
        RUNS[task_id].update(state)

    try:
        summary = core.run_search(slug, progress_cb=cb)
        RUNS[task_id].update(
            {"phase": "fini", "done": True, "summary": summary,
             "message": f"Terminé : {summary['n_new']} nouvelle(s), "
                        f"{summary['n_retenues_new']} retenue(s)"}
        )
    except Exception as exc:  # noqa: BLE001
        RUNS[task_id].update(
            {"phase": "erreur", "done": True,
             "error": f"{type(exc).__name__}: {exc}"}
        )
    finally:
        with _lock:
            ACTIVE.pop(slug, None)


@app.route("/")
def index():
    searches = core.list_searches()
    for s in searches:
        s["stats"] = core.search_stats(s["slug"])
    return render_template("index.html", searches=searches)


@app.route("/searches", methods=["POST"])
def save():
    slug = (request.form.get("slug") or "").strip()
    name = (request.form.get("name") or "").strip()
    # Un champ texte par URL (name="urls" répété) → liste.
    urls = [u.strip() for u in request.form.getlist("urls") if u.strip()]
    critere = (request.form.get("critere") or "").strip()
    if not (name and urls and critere):
        abort(400, "Nom, au moins une URL, et critère sont obligatoires.")
    if slug:
        core.update_search(slug, name, urls, critere)
    else:
        core.create_search(name, urls, critere)
    return redirect(url_for("index"))


@app.route("/searches/<slug>/delete", methods=["POST"])
def delete(slug: str):
    core.delete_search(slug)
    return redirect(url_for("index"))


@app.route("/searches/<slug>/run", methods=["POST"])
def run(slug: str):
    try:
        core.load_search(slug)
    except FileNotFoundError:
        abort(404)
    with _lock:
        if slug in ACTIVE:
            return jsonify({"task_id": ACTIVE[slug], "already_running": True})
        task_id = uuid.uuid4().hex
        ACTIVE[slug] = task_id
    RUNS[task_id] = {"slug": slug, "phase": "démarrage", "current": 0,
                     "total": 0, "message": "Démarrage…", "done": False,
                     "error": None, "summary": None}
    threading.Thread(target=_worker, args=(task_id, slug), daemon=True).start()
    return jsonify({"task_id": task_id})


@app.route("/api/run/<task_id>")
def run_status(task_id: str):
    state = RUNS.get(task_id)
    if state is None:
        abort(404)
    return jsonify(state)


@app.route("/searches/<slug>")
def results(slug: str):
    try:
        search = core.load_search(slug)
    except FileNotFoundError:
        abort(404)
    return render_template(
        "results.html",
        search=search,
        nouveautes=core.nouveautes(slug),
        historique=core.retenues(slug),
        score_min=config.SCORE_MIN,
    )


def main() -> None:
    config.validate()  # fail-fast : valide la config LLM (.env) avant de démarrer
    url = "http://127.0.0.1:5000"
    print(f"lebonparser — interface web sur {url}")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    # use_reloader=False : sinon le serveur démarre deux fois (et ouvre deux onglets).
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
