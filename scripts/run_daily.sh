#!/usr/bin/env bash
# Daily LiteLLM free-model updater.
# 1. regenerate config.yaml via update_free_models.py
# 2. if changed, restart the LiteLLM container and verify health
# 3. commit + push config.yaml and last_report.json
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${ROOT}/logs/daily.log"
mkdir -p "${ROOT}/logs"
exec >>"${LOG}" 2>&1
echo "==== $(date -Is) ===="

cd "${ROOT}"
export PYTHONPATH="${ROOT}"

CHANGED=0
python3 scripts/update_free_models.py && CHANGED=0 || CHANGED=$?
if [ "$CHANGED" -eq 1 ]; then
    echo "[deploy] config changed - restarting proxy"
    podman rm -f gvincent_litellm_1 2>/dev/null || true
    podman-compose -p gvincent -f "${ROOT}/docker-compose.yml" up -d 2>&1 | tail -1
    for i in $(seq 1 60); do
        if curl -s -m 2 http://localhost:4000/health/liveliness 2>/dev/null | grep -q alive; then
            echo "[deploy] proxy healthy after ~${i}s"
            break
        fi
        sleep 1
    done
fi

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git add config.yaml last_report.json scripts/ 2>/dev/null || true
    if ! git diff --cached --quiet; then
        git commit -m "chore: refresh free models $(date '+%Y-%m-%d')" >/dev/null 2>&1 || true
        git push origin HEAD 2>&1 | tail -1 || true
        echo "[git] committed + pushed"
    else
        echo "[git] nothing to commit"
    fi
fi