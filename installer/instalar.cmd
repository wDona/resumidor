@echo off
rem Lo ejecuta el instalador: Python + librerias dentro de la carpeta de la app (desinstalacion limpia)
cd /d "%~dp0"
set UV_PYTHON_DOWNLOADS=never
set UV_CACHE_DIR=%~dp0.uv-cache
tools\uv.exe sync --frozen --python python\python.exe > instalacion.log 2>&1
echo %errorlevel% > instalacion.done
