"""Baja a bin/ ffmpeg + llama.cpp (+ uv en Windows con --uv) para este SO/arquitectura. Solo stdlib; lo usan CI y devs.
Uso: python tools/fetch_bins.py [--target win-x64|linux-x64|macos-arm64|macos-x64] [--uv]"""
import argparse, io, platform, shutil, sys, tarfile, urllib.request, zipfile
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
LLAMA = "b11690"
LL = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA}/llama-{LLAMA}-bin-"
LLAMA_ASSET = {"win-x64": "win-cpu-x64.zip", "linux-x64": "ubuntu-x64.tar.gz", "macos-arm64": "macos-arm64.tar.gz", "macos-x64": "macos-x64.tar.gz"}
# ffmpeg: Windows = gyan.dev "release essentials" (GPL, https://www.gyan.dev/ffmpeg/builds/, fuentes en https://ffmpeg.org);
# Linux = estático de johnvansickle. macOS: sin descarga fiable verificada -> ffmpeg del sistema (brew install ffmpeg).
FFMPEG = {"win-x64": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
          "linux-x64": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"}
PY = "https://github.com/astral-sh/python-build-standalone/releases/download/20261013/cpython-3.12.15%2B20261013-x86_64-pc-windows-msvc-install_only.tar.gz"
UV = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
KEEP = {"ffmpeg", "ffmpeg.exe", "ffprobe", "ffprobe.exe", "uv.exe", "LICENSE", "LICENSE.txt", "GPLv3.txt", "README.txt"}


def detect():
    os_ = {"Windows": "win", "Linux": "linux", "Darwin": "macos"}[platform.system()]
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    return f"{os_}-{arch}"


def get(url):
    print("descargando", url, flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "actas-fetch-bins"})
    return io.BytesIO(urllib.request.urlopen(req, timeout=120).read())


def extract(data, url, dest, only=None):
    """Descomprime en dest (solo ficheros de `only` por nombre si se da, sin subcarpetas)."""
    dest.mkdir(parents=True, exist_ok=True)
    if url.endswith(".zip"):
        with zipfile.ZipFile(data) as z:
            for n in z.namelist():
                name = Path(n).name
                if n.endswith("/") or (only and name not in only):
                    continue
                if only:
                    (dest / name).write_bytes(z.read(n))
                else:
                    z.extract(n, dest)
    else:
        with tarfile.open(fileobj=data) as t:
            if only:
                for m in t.getmembers():
                    if m.isfile() and Path(m.name).name in only:
                        (dest / Path(m.name).name).write_bytes(t.extractfile(m).read())
            else:
                t.extractall(dest, filter="data")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=detect())
    ap.add_argument("--uv", action="store_true", help="también uv.exe (instalador de Windows)")
    a = ap.parse_args()
    t = a.target
    if not any((BIN / f"llama-{LLAMA}").glob("llama-server*")):
        extract(get(LL + LLAMA_ASSET[t]), LLAMA_ASSET[t], BIN / f"llama-{LLAMA}")
    if not any((BIN / "ffmpeg").glob("ffmpeg*")):
        if t in FFMPEG:
            extract(get(FFMPEG[t]), FFMPEG[t], BIN / "ffmpeg", KEEP)
        elif not shutil.which("ffmpeg"):
            sys.exit("macOS: instala ffmpeg del sistema (brew install ffmpeg)")
    if a.uv:  # Windows: CPython empaquetado (uv no instala el suyo: evita las uniones de directorio que RedirectionGuard bloquea, error 448)
        if not (BIN / "python" / "python.exe").exists():
            extract(get(PY), PY, BIN / "_py")
            (BIN / "_py" / "python").rename(BIN / "python")
            (BIN / "_py").rmdir()
        extract(get(UV), UV, BIN / "uv", {"uv.exe"})
    for p in sorted(BIN.glob("*/*server*")) + sorted(BIN.glob("*/ffmpeg*")) + sorted(BIN.glob("*/uv*")):
        print("ok", p.relative_to(BIN))


if __name__ == "__main__":
    main()
