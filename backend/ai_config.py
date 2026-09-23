"""OpenAI configuration; read only backend/.env, never log or mutate credentials."""
from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import shlex

ENV_FILE = Path(__file__).resolve().with_name(".env")
DEFAULT_MODEL = "gpt-4.1-mini-2025-04-14"
CONFIG_KEYS = {"OPENAI_API_KEY", "OPENAI_MODEL", "AIZAK_AI_ENABLED", "AIZAK_AI_TIMEOUT_SECONDS"}


@dataclass(frozen=True)
class AIConfig:
    api_key: str = field(default="", repr=False)
    model: str = DEFAULT_MODEL
    enabled: bool = True
    timeout: float = 8.0
    valid: bool = True


def load_ai_config(*, environ=None, env_file=None):
    """Environment overrides .env, including an explicitly empty API key.

    Supports single-line KEY=value, quoted values, comments and optional export.
    No variable interpolation, shell execution or directory-wide .env discovery.
    """
    environment = os.environ if environ is None else environ
    path = ENV_FILE if env_file is None else Path(env_file)
    values = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        lines = []
    except (OSError, UnicodeError):
        return AIConfig(valid=False)
    try:
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            name, separator, raw = line.partition("=")
            name = name.strip()
            if name not in CONFIG_KEYS:
                continue
            if not separator:
                raise ValueError("Invalid configuration")
            tokens = shlex.split(raw, comments=True, posix=True)
            if len(tokens) > 1:
                raise ValueError("Invalid configuration")
            values[name] = tokens[0] if tokens else ""
        values.update({key: environment[key] for key in CONFIG_KEYS if key in environment})
        enabled = values.get("AIZAK_AI_ENABLED", "true").strip().lower()
        if enabled not in {"true", "false", "1", "0", "yes", "no"}:
            raise ValueError("Invalid configuration")
        timeout = float(values.get("AIZAK_AI_TIMEOUT_SECONDS", "8"))
        if not math.isfinite(timeout) or not 0.1 <= timeout <= 8:
            raise ValueError("Invalid configuration")
        return AIConfig(
            api_key=values.get("OPENAI_API_KEY", "").strip(),
            model=values.get("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            enabled=enabled in {"true", "1", "yes"}, timeout=timeout,
        )
    except (ValueError, TypeError):
        return AIConfig(valid=False)
