"""JSON configuration manager."""
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("config_manager")


def _default_config() -> dict[str, Any]:
    return {"ports": [], "service_running": False}


def load_config(path: str = "config.json") -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        data = _default_config()
        save_config(data, path)
        return data
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("Failed to load config %s: %s, using defaults", path, e)
        return _default_config()


def save_config(data: dict[str, Any], path: str = "config.json") -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("Config saved to %s", path)