# Modo servidor (docs/servidor.md): la app para todo el equipo, desplegada en Coolify u otro Docker.
# Sin IA local: las reuniones se procesan en el escritorio y se envían al servidor.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY *.py ./
COPY static ./static

ENV ACTAS_SERVIDOR=1 \
    ACTAS_WORK=/data \
    ACTAS_PORT=8000 \
    ACTAS_NO_BROWSER=1 \
    ACTAS_NO_EMBED=1 \
    PYTHONUTF8=1 \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ping', timeout=3)"
CMD ["/app/.venv/bin/python", "app.py"]
