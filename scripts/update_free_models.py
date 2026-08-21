#!/usr/bin/env python3
"""Daily updater for LiteLLM free-model config.

Sources:
  1. models.dev/api.json              -> authoritative input/output cost per model (opencode section)
  2. https://opencode.ai/zen/v1/models -> models the current key can list
  3. live probe of each candidate      -> only keep models that answer with cost == 0

Output:
  config.yaml (model_list + smart-router), <repo>/last_report.json
Exit code 0 if no change, 1 if config was regenerated.
"""
import datetime
import json
import os
import pathlib
import sys
import time
import urllib.request
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
CONFIG = ROOT / "config.yaml"
REPORT = ROOT / "last_report.json"

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
MODELS_DEV = "https://models.dev/api.json"
ZEN_MODELS = "https://opencode.ai/zen/v1/models"
ZEN_CHAT = "https://opencode.ai/zen/v1/chat/completions"

# Last known-good live models (fallback if discovery fails entirely).
KNOWN_FALLBACK = ["deepseek-v4-flash-free", "nemotron-3-ultra-free", "mimo-v2.5-free",
                  "big-pickle", "ling-3.0-flash-free", "ling-3.0-tiny-free",
                  "laguna-s-2.1-free", "longcat-2.0-free"]

# Router bucket -> preferred models (only those actually live are kept).
ROUTER_BUCKETS = {
    "SIMPLE":    ["ling-3.0-tiny-free", "laguna-s-2.1-free"],
    "MEDIUM":    ["deepseek-v4-flash-free", "mimo-v2.5-free"],
    "COMPLEX":   ["big-pickle", "ling-3.0-flash-free"],
    "REASONING": ["nemotron-3-ultra-free"],
}
ROUTER_KEYWORDS = [
    {"keywords": ["hi", "hello", "hey", "thanks", "ok", "yes", "what time", "who are you"], "tier": "SIMPLE"},
    {"keywords": ["debug", "race condition", "deadlock", "github ci", "dependency", "migration"], "tier": "REASONING"},
    {"keywords": ["summarize", "summarize the email"], "tier": "MEDIUM"},
    {"keywords": ["k8s", "kubernetes", "distributed", "staging", "production", "architecture"], "tier": "COMPLEX"},
]
ROUTER_TECH_KEYWORDS = ["kubernetes", "docker", "github", "postgresql", "snowflake", "java", "python"]


def get_opencode_key() -> str:
    env_key = os.environ.get("OPENCODE_API_KEY", "").strip()
    if env_key:
        return env_key
    if not ENV.exists():
        sys.exit(f"Missing {ENV}")
    for line in ENV.read_text().splitlines():
        if line.startswith("OPENCODE_API_KEY="):
            v = line.split("=", 1)[1].strip()
            if v and "REPLACE" not in v:
                return v
    sys.exit("OPENCODE_API_KEY missing/unset in .env")


def fetch_json(url, key=None, timeout=30):
    headers = {"User-Agent": UA}
    if key:
        headers["Authorization"] = f"Bearer {key}"
        headers["Content-Type"] = "application/json"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)


def free_from_models_dev() -> set:
    d = fetch_json(MODELS_DEV)
    oc = d.get("opencode", {}).get("models", {})
    return {m for m, v in oc.items()
            if (v.get("cost") or {}).get("input") == 0
            and (v.get("cost") or {}).get("output") == 0}


def served_by_zen(key: str) -> set:
    d = fetch_json(ZEN_MODELS, key=key)
    return {m["id"] for m in d.get("data", [])}


def probe(model: str, key: str, timeout: int = 60) -> bool:
    import json
    body = json.dumps({"model": model,
                       "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
                       "max_tokens": 512}).encode()
    req = urllib.request.Request(ZEN_CHAT, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
            content = d["choices"][0]["message"].get("content") or ""
            cost = d.get("cost")
            return len(content) > 0 and cost in (0, "0", 0.0)
    except Exception:
        return False
    finally:
        time.sleep(0.4)


# Tier order from most- to least-capable; a model that overflows its context
# falls back to the next tiers down, cheapest/smallest-context last.
TIER_ORDER = ["REASONING", "COMPLEX", "MEDIUM", "SIMPLE"]


def build_context_window_fallbacks(tiers: dict) -> list:
    def as_list(v):
        return v if isinstance(v, list) else [v] if v else []

    fallbacks = []
    for i, tier in enumerate(TIER_ORDER):
        models = as_list(tiers.get(tier))
        if not models:
            continue
        lower = [m for t in TIER_ORDER[i + 1:] for m in as_list(tiers.get(t))]
        if lower:
            for m in models:
                fallbacks.append({m: list(lower)})
    return fallbacks


def build_config(live: list) -> dict | None:
    if not live:
        return None
    tiers = {}
    for name, bucket in ROUTER_BUCKETS.items():
        avail = [f"zen-{m}" for m in bucket if m in live]
        tiers[name] = avail[0] if len(avail) == 1 else avail
    default = "zen-deepseek-v4-flash-free" if "deepseek-v4-flash-free" in live else live[0]

    model_list = [{"model_name": f"zen-{m}", "litellm_params": {
        "model": f"openai/{m}", "api_base": "https://opencode.ai/zen/v1",
        "api_key": "os.environ/OPENCODE_API_KEY"}} for m in live]
    model_list.append({"model_name": "smart-router", "litellm_params": {
        "model": "auto_router/complexity_router", "drop_params": True,
        "complexity_router_config": {
            "tiers": tiers,
            "keyword_tier_rules": ROUTER_KEYWORDS,
            "custom_technical_keywords": ROUTER_TECH_KEYWORDS},
        "complexity_router_default_model": default}})
    return {"model_list": model_list,
            "router_settings": {"routing_strategy": "usage-based-routing-v2",
                                "num_retries": 2, "cooldown_time": 10, "timeout": 60,
                                "context_window_fallbacks": build_context_window_fallbacks(tiers)},
            "litellm_settings": {}, "general_settings": {"health_check_interval": 30}}


def main() -> int:
    from yaml import dump

    key = get_opencode_key()
    free = free_from_models_dev()
    try:
        served = served_by_zen(key)
        candidates = sorted(free & served)
    except Exception:
        candidates = sorted(free)
    if not candidates:
        candidates = sorted(free)

    live = [m for m in candidates if probe(m, key)]
    if not live:
        live = [m for m in KNOWN_FALLBACK if m in free]

    now = datetime.datetime.now().astimezone().isoformat()
    report = {"generated_at": now, "candidates": candidates,
              "live": live, "dead": sorted(set(candidates) - set(live))}
    REPORT.write_text(json.dumps(report, indent=2))

    cfg = build_config(live)
    if cfg is None:
        sys.exit("No live models - refusing to overwrite config")
    header = f"# Auto-generated by scripts/update_free_models.py on {now}\n# Do not edit manually.\n"
    new_text = header + dump(cfg, sort_keys=False)

    if CONFIG.exists() and CONFIG.read_text() == new_text:
        print(f"[ok] No change - {len(live)} free models still live")
        return 0
    CONFIG.write_text(new_text)
    print(f"[updated] wrote config with {len(live)} free models: {live}")
    return 1


if __name__ == "__main__":
    sys.exit(main())