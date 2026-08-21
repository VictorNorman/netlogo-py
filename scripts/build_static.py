"""Builds a fully static deploy bundle (dist/) with only the WASM engine
-- e.g. for Firebase Hosting, which serves plain files and can't run this
app's FastAPI server. Run from the repo root:

    python3 scripts/build_static.py

Reuses server/main.py's own MODEL_REGISTRY -- importing it runs the exact
same model-discovery/registry-building code /api/models computes live --
so nothing here hand-duplicates that logic. The two genuinely dynamic
things a live server would otherwise compute per request get written out
as plain files instead, once, at build time:
  - dist/models.json -- the same shape /api/models returns, except
    "engines" is empty. There's no server here to run "server-side" on;
    static/app.js's engine dropdown always appends its own "wasm" option
    regardless of what the server sends, so an empty list here is
    exactly what makes wasm the only choice.
  - dist/model-source/<key>.py -- one plain-text file per model, what
    /api/model-source used to read live on request.
Everything else static/app.js needs (static/*, /py/engine/*) is just
copied over unchanged -- see static/app.js's staticMode fallback, which
is what notices /api/models isn't reachable at all and switches to these
files instead.
"""

import json
import pathlib
import shutil
import sys

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
DIST_DIR = BASE_DIR / "dist"

sys.path.insert(0, str(BASE_DIR))
import server.main as server_main  # noqa: E402 -- needs BASE_DIR on sys.path first


def build():
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True)

    # static/* -> dist/static/*, then index.html moves up to dist/index.html
    # -- the same split server/main.py's own "/" route + "/static" mount
    # already serve today (see its FileResponse/StaticFiles calls).
    shutil.copytree(BASE_DIR / "static", DIST_DIR / "static")
    shutil.move(str(DIST_DIR / "static" / "index.html"), str(DIST_DIR / "index.html"))

    # engine/*.py -> dist/py/engine/*.py, matching the /py/engine mount
    # pyodide-worker.js's ENGINE_FILES fetches from.
    engine_dir = DIST_DIR / "py" / "engine"
    engine_dir.mkdir(parents=True)
    for name in ("__init__.py", "netlogo.py"):
        shutil.copy(BASE_DIR / "engine" / name, engine_dir / name)

    # One plain-text .py file per model, standing in for /api/model-source.
    source_dir = DIST_DIR / "model-source"
    source_dir.mkdir(parents=True)
    for key in server_main.MODEL_REGISTRY:
        shutil.copy(BASE_DIR / "models" / f"{key}.py", source_dir / f"{key}.py")

    # models.json -- /api/models's own live response shape, minus a
    # working "server-side" engine entry (there's nothing here to run it).
    models_json = {
        "active": server_main.active_model_key,
        "active_engine": "wasm",
        "engines": [],
        "models": [
            {
                "key": key,
                "label": entry["label"],
                "sliders": entry["sliders"],
                "switches": entry["switches"],
                "choosers": entry["choosers"],
                "monitors": entry["monitors"],
                "plots": entry["plots"],
                "info": entry["info"],
            }
            for key, entry in server_main.MODEL_REGISTRY.items()
        ],
    }
    (DIST_DIR / "models.json").write_text(json.dumps(models_json, indent=2))

    print(f"Static build written to {DIST_DIR}")


if __name__ == "__main__":
    build()
