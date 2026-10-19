#!/bin/bash
# Uso (en macOS, desde la raíz, tras `python3 tools/fetch_bins.py --uv`): installer/macos/build.sh <arm64|x64> <versión>
# Deja installer/Output/Actas-<arch>.dmg (sin firmar ni notarizar: firma ad hoc para que arranque en Apple Silicon)
set -euo pipefail
ARCH=$1; VER=${2:-0.0.0}; VER=${VER#v}
APP=installer/Output/dmg/Actas.app
rm -rf installer/Output/dmg && mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/app/bin"
sed "s/@VERSION@/$VER/" installer/macos/Info.plist >"$APP/Contents/Info.plist"
cp installer/macos/Actas "$APP/Contents/MacOS/Actas"
R="$APP/Contents/Resources"
echo "$VER" >"$R/VERSION"
cp app.py pipeline.py rag.py models.py pyproject.toml uv.lock .python-version README.md "$R/app/"
cp -R static "$R/app/static"
cp -R bin/ffmpeg bin/llama-* "$R/app/bin/"
cp -R bin/python "$R/python"
cp bin/uv/uv "$R/uv"
codesign --force --deep -s - "$APP"
ln -s /Applications installer/Output/dmg/Applications
for i in 1 2 3 4 5; do  # hdiutil falla a veces con "Resource busy" en los runners
  hdiutil create -volname Actas -srcfolder installer/Output/dmg -ov -format UDZO "installer/Output/Actas-$ARCH.dmg" && break
  sleep 10
done
ls -lh installer/Output/Actas-"$ARCH".dmg
