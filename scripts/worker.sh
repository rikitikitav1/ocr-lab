#!/bin/sh
# copy the code the worker will run; it restarts itself onto newer code once the queue is empty
set -e
rm -rf /tmp/worker-code.*
snapshot=$(mktemp -d /tmp/worker-code.XXXXXX)
cp -r /app/app /app/config "$snapshot"/
find "$snapshot" -name __pycache__ -prune -exec rm -rf {} +
exec env SOURCE_DIR=/app python "$snapshot/app/worker.py"
