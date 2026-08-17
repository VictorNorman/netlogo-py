/**
 * Web Worker running Pyodide (CPython + NumPy compiled to WebAssembly) so
 * the "WASM (browser)" engine can execute a model entirely client-side,
 * and so the user can edit a model's Python source in the browser and
 * re-run it immediately (NetLogo-style "edit, recompile, go").
 *
 * Important: this worker does NOT compile the edited script into its own
 * WASM module on every edit. The one WASM binary is the CPython+NumPy
 * runtime loaded once below; edited Python text is just interpreted by
 * it, the same way server/main.py's model.setup()/go() runs the
 * server-side engines, just here in the browser. That's what makes
 * edit -> run fast: there is no compile step at all, on any edit.
 *
 * Protocol: the main thread posts {id, type, payload}; this worker always
 * replies with exactly one {id, ok: true, data} or {id, ok: false, error}.
 */

const PYODIDE_VERSION = "v0.26.4"; // bump as needed: https://pyodide.org/en/stable/project/changelog.html
importScripts(`https://cdn.jsdelivr.net/pyodide/${PYODIDE_VERSION}/full/pyodide.js`);

// Every model script does `from engine.netlogo import *`, which first
// imports the `engine` package itself -- both files need to exist before
// that can succeed, mirroring the package layout of the repo's engine/
// directory (see engine/__init__.py: it used to also import an OOP engine
// and a vectorized-NumPy engine, both removed once no model needed them).
const ENGINE_FILES = ["__init__.py", "netlogo.py"];

// Defined once inside the Pyodide interpreter at init time; the main
// thread's messages call these directly (via pyodide.globals.get(...))
// instead of re-implementing a command grammar in Python per message.
const BOOTSTRAP_PY = `
import sys
if "" not in sys.path:
    sys.path.insert(0, "")

_model = None

class _ModuleAdapter:
    # Every model (fire.py, ...) is a plain module -- setup()/go()/
    # is_running() as free functions plus top-level globals, no class at
    # all (see engine/netlogo.py's module docstring for why). This wraps
    # that module's exec() namespace so everything below can keep treating
    # _model uniformly via ordinary attribute access -- hasattr/setattr/
    # method calls all work the same whether _model is a real instance or
    # one of these, exactly as server/main.py's endpoints do for the real
    # module on the server side.
    def __init__(self, ns):
        object.__setattr__(self, "_ns", ns)

    def __getattr__(self, name):
        if name in self._ns:
            return self._ns[name]
        raise AttributeError(name)

    def __setattr__(self, name, value):
        self._ns[name] = value

    def state(self):
        # A real method (not routed through __getattr__ above, which only
        # fires when normal lookup fails) so this always wins even when
        # the wrapped script defines its own state -- same fallback rule
        # as server/main.py's _state(): use the script's own state() if it
        # has one, else build it automatically. See engine/netlogo.py's
        # auto_state().
        if "state" in self._ns:
            return self._ns["state"]()
        from engine.netlogo import auto_state
        return auto_state(module=self._ns)

def _model_state():
    if _model is None:
        return None
    return {**_model.state(), "running": _model.is_running()}

def _run_script(source, class_name, params):
    global _model
    ns = {}
    exec(compile(source, "<edited-script>", "exec"), ns)
    if class_name and class_name in ns:
        cls = ns[class_name]
        _model = cls(**dict(params))
    else:
        _model = _ModuleAdapter(ns)
        for key, value in dict(params).items():
            if key in ns:
                setattr(_model, key, value)
        _model.setup()
    return _model_state()

def _do_setup(params):
    for key, value in dict(params).items():
        if hasattr(_model, key):
            setattr(_model, key, value)
    _model.setup()
    return _model_state()

def _do_step():
    _model.go()
    return _model_state()

def _do_set_param(name, value):
    ok = hasattr(_model, name)
    if ok:
        setattr(_model, name, value)
    return {"ok": ok, "state": _model_state()}

def _do_mouse(xcor, ycor, down, inside):
    # Mirrors server/main.py's /api/mouse exactly -- see its own comment
    # for why draw_cells() specifically.
    from engine.netlogo import set_mouse_state
    set_mouse_state(xcor, ycor, down, inside)
    if hasattr(_model, "draw_cells"):
        _model.draw_cells()
    return _model_state()
`;

let pyodideInstance = null;
let pyodideReadyPromise = null;
let pyFns = null;

async function fetchText(url) {
  // no-store: these engine/*.py files are the interpreter's own runtime
  // code, not simulation data, and this worker only ever fetches them
  // once per Worker lifetime (see ensurePyodide()) -- so a cached-but-
  // stale response here means silently running old engine code with no
  // way to tell. Browsers differ on whether a page reload forces revalidation
  // of a Worker's own fetch()es (observed: Chrome does, Firefox doesn't),
  // so don't rely on reload semantics at all -- always hit the network.
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`failed to fetch ${url}: ${response.status}`);
  }
  return response.text();
}

async function initPyodide() {
  const pyodide = await loadPyodide();
  await pyodide.loadPackage("numpy");

  // FS.mkdirTree() always resolves its argument from the filesystem root
  // (it does not consult cwd), while FS.writeFile() resolves relative
  // paths against cwd -- so both sides need the same absolute path, or a
  // plain "engine" mkdirTree() and a relative "engine/x.py" writeFile()
  // silently target two different directories and writeFile 404s (ENOENT).
  const engineDir = `${pyodide.FS.cwd()}/engine`;
  pyodide.FS.mkdirTree(engineDir);
  for (const name of ENGINE_FILES) {
    const text = await fetchText(`/py/engine/${name}`);
    pyodide.FS.writeFile(`${engineDir}/${name}`, text);
  }

  pyodide.runPython(BOOTSTRAP_PY);
  pyFns = {
    runScript: pyodide.globals.get("_run_script"),
    doSetup: pyodide.globals.get("_do_setup"),
    doStep: pyodide.globals.get("_do_step"),
    doSetParam: pyodide.globals.get("_do_set_param"),
    doMouse: pyodide.globals.get("_do_mouse"),
    modelState: pyodide.globals.get("_model_state"),
  };
  pyodideInstance = pyodide;
  return pyodide;
}

function ensurePyodide() {
  if (!pyodideReadyPromise) {
    pyodideReadyPromise = initPyodide();
  }
  return pyodideReadyPromise;
}

// Converts a PyProxy dict result (or None -> undefined) into a plain JS
// object, then releases the PyProxy. Every call site below owns exactly
// one PyProxy result, so this is the only place that needs to destroy().
function toJs(pyResult) {
  if (pyResult === null || pyResult === undefined) {
    return null;
  }
  const value = pyResult.toJs({ dict_converter: Object.fromEntries });
  pyResult.destroy();
  return value;
}

const handlers = {
  async init() {
    await ensurePyodide();
    return { ready: true };
  },

  async "run-script"(payload) {
    await ensurePyodide();
    const params = pyodideInstance.toPy(payload.params);
    try {
      return toJs(pyFns.runScript(payload.source, payload.className, params));
    } finally {
      params.destroy();
    }
  },

  async setup(payload) {
    await ensurePyodide();
    const params = pyodideInstance.toPy(payload.params);
    try {
      return toJs(pyFns.doSetup(params));
    } finally {
      params.destroy();
    }
  },

  async step() {
    await ensurePyodide();
    return toJs(pyFns.doStep());
  },

  async mouse(payload) {
    await ensurePyodide();
    return toJs(pyFns.doMouse(payload.xcor, payload.ycor, payload.down, payload.inside));
  },

  async "set-param"(payload) {
    await ensurePyodide();
    const data = toJs(pyFns.doSetParam(payload.name, payload.value));
    return {
      ...data.state,
      ok: data.ok,
    };
  },

  async state() {
    await ensurePyodide();
    return toJs(pyFns.modelState());
  },
};

self.onmessage = async (event) => {
  const { id, type, payload } = event.data;
  const handler = handlers[type];
  if (!handler) {
    self.postMessage({
      id,
      ok: false,
      error: `unknown message type: ${type}`,
    });
    return;
  }
  try {
    const data = await handler(payload || {});
    self.postMessage({
      id,
      ok: true,
      data,
    });
  } catch (err) {
    self.postMessage({
      id,
      ok: false,
      error: (err && err.message) || String(err),
    });
  }
};
