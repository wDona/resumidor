#!/bin/sh
# App de QA con latido (si no, se cierra a los 60 s sin página abierta)
cd /home/wdona/Projects/actas
export ACTAS_WORK=${ACTAS_WORK:-/tmp/actas-qa-work} ACTAS_NO_BROWSER=1 ACTAS_PORT=57377
uv run python app.py & APP=$!
while kill -0 $APP 2>/dev/null; do curl -s -o /dev/null -X POST http://127.0.0.1:57377/api/latido; sleep 15; done
