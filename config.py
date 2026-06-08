"""config.py — load config.yaml into a dict."""
from __future__ import annotations

import os

import yaml


def load_config(path: str = "config.yaml") -> dict:
    """Return the parsed YAML config, or {} if the file is absent."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ without
    overriding already-set variables. Used for SECRET_KEY / GOOGLE_OAUTH_*."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
