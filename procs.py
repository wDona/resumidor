"""Registro de los llama-server que lanzamos: se paran al salir, mueren con el padre y los huérfanos de un
arranque anterior se matan al empezar (solo los de WORK/llama_pids.json que sigan siendo bin/**/llama-*)."""
import atexit, ctypes, json, os, signal, subprocess, sys, threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PIDF = ROOT / "work" / "llama_pids.json"
_REG, _lock, _job = [], threading.Lock(), [None]


def _win_job():
    """Un Job Object de por vida del proceso: al cerrarse (incluso si nos matan) mueren sus hijos."""
    from ctypes import wintypes as w
    if _job[0] is None:
        class Basic(ctypes.Structure):
            _fields_ = [("a", ctypes.c_int64), ("b", ctypes.c_int64), ("LimitFlags", w.DWORD), ("c", ctypes.c_size_t),
                        ("d", ctypes.c_size_t), ("e", w.DWORD), ("f", ctypes.c_size_t), ("g", w.DWORD), ("h", w.DWORD)]

        class Io(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in "abcdef"]

        class Ext(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("Io", Io)] + [(n, ctypes.c_size_t) for n in "abcd"]
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.restype = w.HANDLE
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        h = k.CreateJobObjectW(None, None)
        e = Ext()
        e.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k.SetInformationJobObject(h, 9, ctypes.byref(e), ctypes.sizeof(e))  # JobObjectExtendedLimitInformation
        _job[0] = (k, h)
    return _job[0]


def _pdeathsig():
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG


def _cmdline(pid):
    """Argumentos del proceso vivo `pid` o None."""
    try:
        if sys.platform.startswith("linux"):
            a = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            return [x.decode() for x in a if x] or None
        if os.name == "nt":
            from ctypes import wintypes as w
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.OpenProcess.restype = w.HANDLE
            h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return None
            buf, n = ctypes.create_unicode_buffer(1024), w.DWORD(1024)
            ok = k.QueryFullProcessImageNameW(w.HANDLE(h), 0, buf, ctypes.byref(n))
            k.CloseHandle(w.HANDLE(h))
            return [buf.value] if ok else None
        o = subprocess.run(["ps", "-p", str(pid), "-o", "args="], capture_output=True, text=True).stdout.split()
        return o or None
    except OSError:
        return None


def _save():
    PIDF.parent.mkdir(exist_ok=True)
    PIDF.write_text(json.dumps([{"pid": p.pid, "exe": p.args[0]} for p in _REG if p.poll() is None]))


def spawn(cmd, **kw):
    """Popen de un llama-server: registrado, atado a la vida del padre y anotado en llama_pids.json."""
    if sys.platform.startswith("linux"):
        kw["preexec_fn"] = _pdeathsig
    p = subprocess.Popen(cmd, **kw)
    if os.name == "nt":
        k, h = _win_job()
        k.AssignProcessToJobObject(h, int(p._handle))
    with _lock:
        _REG.append(p)
        _save()
    return p


def kill_all(wait=3):
    with _lock:
        ps = [p for p in _REG if p.poll() is None]
        _REG.clear()
    for p in ps:
        p.terminate()
    for p in ps:
        try:
            p.wait(wait)
        except subprocess.TimeoutExpired:
            p.kill()
    try:
        PIDF.write_text("[]")
    except OSError:
        pass


def cleanup_stale():
    """Mata los llama-server de una ejecución anterior que sigan vivos y sean exactamente el exe que anotamos (bajo bin/)."""
    try:
        old = json.loads(PIDF.read_text())
    except (OSError, ValueError):
        return
    bins = str(ROOT / "bin")
    for r in old:
        a = _cmdline(r["pid"])
        if a and a[0] == r["exe"] and os.path.abspath(a[0]).startswith(bins) and Path(a[0]).name.startswith("llama-"):
            try:
                os.kill(r["pid"], signal.SIGTERM)
            except OSError:
                pass
    try:
        PIDF.write_text("[]")
    except OSError:
        pass


def on_signal(stop=None):
    """SIGTERM/SIGINT (+SIGBREAK, cierre de consola en Windows): para a los hijos y pide `stop()` (p. ej. cerrar uvicorn)."""
    def h(*_):
        kill_all()
        if stop:
            stop()
        else:
            sys.exit(0)
    for n in ("SIGTERM", "SIGINT", "SIGBREAK"):
        if hasattr(signal, n):
            signal.signal(getattr(signal, n), h)


atexit.register(kill_all)
