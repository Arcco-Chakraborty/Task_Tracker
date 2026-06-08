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
