#!/usr/bin/env bash
# the pre-commit gate in one call: full output goes to a log, the terminal gets one line per step and the failures
set -uo pipefail
cd "$(dirname "$0")/.."

LOG="${CHECK_LOG:-temp_files/check.log}"
mkdir -p "$(dirname "$LOG")"
: > "$LOG"
status=0

step() {
  local name=$1; shift
  if "$@" >> "$LOG" 2>&1; then
    echo "$name: ok"
  else
    echo "$name: FAILED"
    status=1
  fi
}

audit() {
  uv export --no-hashes --no-emit-project --format requirements-txt -o temp_files/requirements.txt -q &&
    uvx pip-audit -r temp_files/requirements.txt
}

# the same gitleaks image CI runs, over the whole history
secrets() {
  docker run --rm -v "$PWD":/repo zricethezav/gitleaks:latest detect --source /repo --no-banner --redact
}

step ruff uv run ruff check app tests scripts
step pytest uv run pytest -q -n "${CHECK_WORKERS:-8}" -p no:cacheprovider "$@"
step bandit uvx bandit -r app/ -ll -q -c pyproject.toml
step pip-audit audit
step gitleaks secrets
grep -E "^(FAILED|ERROR) |passed|failed|leaks found|Issue:" "$LOG" | tail -20
echo "log: $LOG"
exit $status
