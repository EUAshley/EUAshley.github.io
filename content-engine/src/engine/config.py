"""Settings and YAML config loading. Secrets come only from the environment."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines). Real env vars always win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(PROJECT_ROOT / ".env")


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value else default


def config_dir() -> Path:
    return Path(env("ENGINE_CONFIG_DIR", str(PROJECT_ROOT / "config")))


def db_url() -> str:
    url = env("ENGINE_DB_URL", "sqlite:///data/engine.db")
    # Resolve relative SQLite paths against the project root, not the cwd.
    prefix = "sqlite:///"
    if url.startswith(prefix) and not url.startswith(prefix + "/") and url != "sqlite:///:memory:":
        path = PROJECT_ROOT / url[len(prefix):]
        path.parent.mkdir(parents=True, exist_ok=True)
        url = prefix + str(path)
    return url


def default_brand_slug() -> str:
    return env("ENGINE_BRAND", "daily-benefit-shorts")


@lru_cache
def scoring_config() -> dict:
    return yaml.safe_load((config_dir() / "scoring.yaml").read_text())


@lru_cache
def brand_config(slug: str) -> dict:
    path = config_dir() / "brands" / f"{slug}.yaml"
    if not path.exists():
        return {"slug": slug, "name": slug, "script_format": [], "hashtags": {}}
    return yaml.safe_load(path.read_text())


def available_brand_configs() -> list[dict]:
    return [yaml.safe_load(p.read_text()) for p in sorted((config_dir() / "brands").glob("*.yaml"))]


def reload() -> None:
    scoring_config.cache_clear()
    brand_config.cache_clear()
