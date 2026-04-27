"""Configuration loader for ATTEST.

Reads attest.yaml, resolves environment variable references (${VAR_NAME}),
and returns a validated AttestConfig object.

Usage:
    from attest.core.config import load_config

    config = load_config()                    # finds attest.yaml in current dir
    config = load_config("path/to/config.yaml")  # explicit path
    config = load_config()                    # returns defaults if no file found
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Union

from dotenv import load_dotenv
from ruamel.yaml import YAML

from attest.core.config_models import AttestConfig
from attest.core.exceptions import ConfigError


# ---------------------------------------------------------------------------
# Environment variable resolution
# ---------------------------------------------------------------------------

# Matches ${VAR_NAME} or $VAR_NAME in strings
_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def _resolve_env_vars(value: Any) -> Any:
    """Replace ${VAR_NAME} references in strings with environment variable values.

    Works recursively on dicts and lists.
    Returns the value unchanged if it's not a string/dict/list.
    """
    if isinstance(value, str):
        def replacer(match):
            var_name = match.group(1) or match.group(2)
            env_value = os.environ.get(var_name)
            if env_value is None:
                # Leave the reference as-is if not found (user might set it later)
                return match.group(0)
            return env_value

        return _ENV_VAR_PATTERN.sub(replacer, value)

    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]

    return value


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------


def _find_config_file(start_dir: Optional[Path] = None) -> Optional[Path]:
    """Look for attest.yaml or attest.yml in the given directory.

    If not found, returns None (we'll use defaults).
    """
    search_dir = start_dir or Path.cwd()
    for name in ["attest.yaml", "attest.yml"]:
        path = search_dir / name
        if path.exists():
            return path
    return None


def _load_yaml_file(path: Path) -> Dict[str, Any]:
    """Read and parse a YAML file. Returns a dict."""
    yaml = YAML()
    yaml.preserve_quotes = True
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.load(f)
        return data if data is not None else {}
    except Exception as e:
        raise ConfigError(f"Failed to parse config file {path}: {e}") from e


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(
    path: Optional[Union[str, Path]] = None,
    load_env: bool = True,
) -> AttestConfig:
    """Load ATTEST configuration from a YAML file.

    Args:
        path: Explicit path to config file. If None, searches for attest.yaml
              in the current directory.
        load_env: Whether to load .env / .env.local files. Defaults to True.

    Returns:
        Validated AttestConfig object with all env vars resolved.

    Examples:
        # Auto-find attest.yaml in current dir
        config = load_config()

        # Explicit path
        config = load_config("my_project/attest.yaml")

        # Returns defaults if no file found
        config = load_config()  # no attest.yaml → all defaults
    """
    # Step 1: Load .env files (so env vars are available for resolution)
    if load_env:
        # .env.local takes priority over .env
        load_dotenv(".env.local", override=True)
        load_dotenv(".env", override=False)

    # Step 2: Find and read the YAML file
    if path is not None:
        config_path = Path(path)
        if not config_path.exists():
            raise ConfigError(f"Config file not found: {config_path}")
        raw_data = _load_yaml_file(config_path)
    else:
        config_path = _find_config_file()
        if config_path is not None:
            raw_data = _load_yaml_file(config_path)
        else:
            # No config file found — use all defaults
            raw_data = {}

    # Step 3: Resolve environment variable references
    resolved_data = _resolve_env_vars(raw_data)

    # Step 4: Validate and return
    try:
        return AttestConfig(**resolved_data)
    except Exception as e:
        raise ConfigError(f"Invalid configuration: {e}") from e


def get_agent_config(config: AttestConfig, agent_name: str):
    """Get configuration for a specific agent by name.

    Args:
        config: The loaded AttestConfig.
        agent_name: Name of the agent (key in agents dict).

    Returns:
        AgentConfig for the named agent.

    Raises:
        ConfigError if agent not found.
    """
    if agent_name not in config.agents:
        available = list(config.agents.keys())
        raise ConfigError(
            f"Agent '{agent_name}' not found in config. "
            f"Available agents: {available}"
        )
    return config.agents[agent_name]
