# LiteLLM Free-Model Gateway

Self-hosted [LiteLLM](https://docs.litellm.ai) proxy (podman) exposing **free** LLM models via OpenCode Zen, with a complexity-based auto-router.

## What's here

- `config.yaml` — **auto-generated**. `model_list` of free Zen models + `smart-router` (SIMPLE / MEDIUM / COMPLEX / REASONING tiers). Do not edit manually.
- `docker-compose.yml` — proxy + Postgres, reads secrets from `.env`.
- `.env.example` — copy to `.env` (gitignored) and set `OPENCODE_API_KEY` (get it from `~/.local/share/opencode/auth.json`).
- `scripts/update_free_models.py` — discovers free models (models.dev + Zen `/models`), live-probes each, regenerates `config.yaml`.
- `scripts/run_daily.sh` — cron entrypoint: runs the updater, restarts the proxy if config changed, commits + pushes.
- `last_report.json` — last discovery run (candidates / live / dead).

## Daily model refresh (GitHub Actions + local deploy)

Split so it costs $0 and needs no always-on compute from Actions:

1. **GitHub Actions** (`.github/workflows/update-free-models.yml`, cron 03:30 UTC + manual dispatch) runs `scripts/update_free_models.py` with the `OPENCODE_API_KEY` secret, regenerates `config.yaml`, self-commits and pushes (heartbeat commit keeps the 60-day inactivity timer from disabling the schedule).
2. **Local cron** (`*/15 * * * *`) runs `scripts/pull_deploy.sh` — pulls `main` and restarts the proxy container only when `config.yaml` changed.

The proxy itself stays on this host (GitHub runners are ephemeral and can't host it).

## Usage

```bash
# proxy up:
podman-compose -p gvincent -f docker-compose.yml up -d
# chat (direct or via smart-router):
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-1234" \
  -d '{"model":"smart-router","messages":[{"role":"user","content":"hi"}]}'
```

Cron (installed): `*/15 * * * * /home/gvincent/litellm/scripts/pull_deploy.sh` — pulls `main`, restarts the proxy if `config.yaml` changed. Model discovery runs in GitHub Actions (03:30 UTC daily).