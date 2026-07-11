"""配置加载。"""
import os
import yaml

from .utils import BASE_DIR


def load_config(path: str = None) -> dict:
    path = path or os.path.join(BASE_DIR, "config.yaml")
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg or {}
