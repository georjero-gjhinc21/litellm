#!/usr/bin/env bash
# Populates .env from Bitwarden immediately before the proxy starts.
# Requires: `bw` CLI on PATH, and BW_CLIENTID / BW_CLIENTSECRET / BW_PASSWORD
# set in the environment of whatever runs this (interactive shell or the
# cron job's own env - never written to disk by this script).
#
# Vault items expected (Login type unless noted):
#   LiteLLM - Master Key      password = LITELLM_MASTER_KEY
#   LiteLLM - Salt Key        password = LITELLM_SALT_KEY
#   LiteLLM - UI Login        username = UI_USERNAME, password = UI_PASSWORD
#   LiteLLM - OpenCode Zen Key  password = OPENCODE_API_KEY
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

command -v bw >/dev/null || { echo "[bitwarden] bw CLI not found on PATH" >&2; exit 1; }
command -v jq >/dev/null || { echo "[bitwarden] jq not found on PATH" >&2; exit 1; }
: "${BW_CLIENTID:?BW_CLIENTID not set}"
: "${BW_CLIENTSECRET:?BW_CLIENTSECRET not set}"
: "${BW_PASSWORD:?BW_PASSWORD not set}"

bw login --apikey --quiet 2>/dev/null || true
BW_SESSION=$(bw unlock "$BW_PASSWORD" --raw)
bw sync --session "$BW_SESSION" >/dev/null

get_pw() { bw get password "$1" --session "$BW_SESSION"; }
get_field() { bw get item "$1" --session "$BW_SESSION" | jq -r ".fields[] | select(.name==\"$2\") | .value"; }

umask 077
cat > .env <<EOF
LITELLM_MASTER_KEY=$(get_pw 'LiteLLM - Master Key')
LITELLM_SALT_KEY=$(get_pw 'LiteLLM - Salt Key')
UI_USERNAME=$(get_field 'LiteLLM - UI Login' username)
UI_PASSWORD=$(get_pw 'LiteLLM - UI Login')
OPENCODE_API_KEY=$(get_pw 'LiteLLM - OpenCode Zen Key')
EOF

bw lock --session "$BW_SESSION" >/dev/null
echo "[bitwarden] .env populated from vault"
