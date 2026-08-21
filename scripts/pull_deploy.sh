#!/usr/bin/env bash
# Local deploy step of the daily pipeline.
# GitHub Actions does model discovery + commits config.yaml.
# This host: pull latest config and restart the proxy if it changed.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${ROOT}/logs/deploy.log"
mkdir -p "${ROOT}/logs"
exec >>"${LOG}" 2>&1
echo "==== $(date -Is) ===="

cd "${ROOT}"
old_sha=$(git rev-parse HEAD 2>/dev/null || echo none)
git pull --ff-only --quiet 2>&1 || echo "[git] pull failed - will retry next cycle"

new_sha=$(git rev-parse HEAD 2>/dev/null || echo none)
if [ "$old_sha" = "$new_sha" ]; then
    echo "[deploy] no new config"; exit 0
fi

changed=0
git diff --quiet "$old_sha" "$new_sha" -- config.yaml 2>/dev/null || changed=1
if [ "$changed" -eq 1 ]; then
    echo "[deploy] config.yaml changed - restarting proxy"
    if [ -n "${BW_CLIENTID:-}" ] && [ -n "${BW_CLIENTSECRET:-}" ] && [ -n "${BW_PASSWORD:-}" ]; then
        "${ROOT}/scripts/load_secrets_from_bitwarden.sh" || echo "[deploy] WARNING: Bitwarden fetch failed - using existing .env if present"
    elif [ ! -f "${ROOT}/.env" ]; then
        echo "[deploy] WARNING: no .env and no BW_CLIENTID/BW_CLIENTSECRET/BW_PASSWORD in env - proxy cannot start"
    fi
    podman rm -f gvincent_litellm_1 2>/dev/null || true
    podman-compose -p gvincent -f "${ROOT}/docker-compose.yml" up -d 2>&1 | tail -1
    for i in $(seq 1 60); do
        if curl -s -m 2 http://localhost:4000/health/liveliness 2>/dev/null | grep -q alive; then
            echo "[deploy] proxy healthy after ~${i}s"; break
        fi
        sleep 1
    done
    # .env is only needed at container-creation time; podman has already
    # copied the values into the running container's own env, so shred the
    # host-disk copy rather than leaving decrypted secrets sitting there.
    if [ -n "${BW_CLIENTID:-}" ]; then
        shred -u "${ROOT}/.env" 2>/dev/null || rm -f "${ROOT}/.env"
    fi
else
    echo "[deploy] no config.yaml change - nothing to restart"
fi