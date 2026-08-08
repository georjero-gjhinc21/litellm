# LiteLLM Free-Model Gateway

Self-hosted [LiteLLM](https://docs.litellm.ai) proxy (podman) exposing **free** LLM models via OpenCode Zen, with a complexity-based auto-router.

## What's here

- `config.yaml` — **auto-generated**. `model_list` of free Zen models + `smart-router` (SIMPLE / MEDIUM / COMPLEX / REASONING tiers). Do not edit manually.
- `docker-compose.yml` — proxy + Postgres, reads secrets from `.env`.
- `.env.example` — copy to `.env` (gitignored) and set `OPENCODE_API_KEY` (get it from `~/.local/share/opencode/auth.json`).
- `scripts/update_free_models.py` — discovers free models (models.dev + Zen `/models`), live-probes each, regenerates `config.yaml`.
- `scripts/run_daily.sh` — cron entrypoint: runs the updater, restarts the proxy if config changed, commits + pushes.
- `last_report.json` — last discovery run (candidates / live / dead).

## Usage

```bash
podman-compose -p gvincent up -d
curl http://localhost:4000/v1/chat/completions \   # or via smart-router
  -H "Authorization: Bearer sk-1234" \
  -d '{"model":"zen-deepseek-v4-flash-free","messages":[{"role":"user","content":"hi"}]}'
```

Cron (installed): `30 3 * * * /home/gvincent/litellm/scripts/run_daily.sh` — daily 03:30 refresh + auto-deploy + push.