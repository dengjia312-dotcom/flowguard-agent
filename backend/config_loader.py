import json
from pathlib import Path
from typing import Dict, Any


class ConfigLoader:
    """
    Loads and caches agent.config.json.
    API keys are read from environment variables (via python-dotenv in main.py),
    never from the config file itself.
    """

    _config: Dict[str, Any] = {}

    @classmethod
    def load(cls, config_path: str = "agent.config.json") -> Dict[str, Any]:
        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(
                f"Config file not found: {config_path}. "
                f"Make sure you run uvicorn from the flowguard-agent/ directory."
            )
        with open(config_file, "r", encoding="utf-8") as f:
            cls._config = json.load(f)
        return cls._config

    @classmethod
    def get(cls) -> Dict[str, Any]:
        if not cls._config:
            return cls.load()
        return cls._config
