"""Project-level configuration via .acorn.toml files."""
import os
from pathlib import Path


def find_project_config(working_dir: str) -> Path | None:
    """Walks up from working_dir looking for .acorn.toml."""
    current = Path(working_dir).resolve()
    while current != current.parent:
        config_file = current / ".acorn.toml"
        if config_file.exists():
            return config_file
        current = current.parent
    return None


def load_project_config(working_dir: str) -> dict:
    """Loads .acorn.toml if present, returns settings overrides."""
    config_path = find_project_config(working_dir)
    if not config_path:
        return {}

    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            return {}

    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        return data
    except Exception:
        return {}


def apply_project_config(settings, config: dict):
    """Applies project config overrides to settings."""
    if not config:
        return

    if "model" in config:
        model_cfg = config["model"]
        if "pro" in model_cfg:
            settings.model = model_cfg["pro"]
        if "flash" in model_cfg:
            settings.flash_model = model_cfg["flash"]
        if "temperature" in model_cfg:
            settings.temperature = model_cfg["temperature"]
        if "max_output_tokens" in model_cfg:
            settings.max_output_tokens = model_cfg["max_output_tokens"]

    if "routing" in config:
        routing_cfg = config["routing"]
        if "enabled" in routing_cfg:
            settings.use_smart_routing = routing_cfg["enabled"]
        if "threshold" in routing_cfg:
            settings.routing_threshold = routing_cfg["threshold"]

    if "permissions" in config:
        perm_cfg = config["permissions"]
        if "safe_commands" in perm_cfg:
            settings.safe_commands.extend(perm_cfg["safe_commands"])
        if "blocked_commands" in perm_cfg:
            settings.blocked_commands.extend(perm_cfg["blocked_commands"])
        if "rules" in perm_cfg:
            settings.permission_rules.update(perm_cfg["rules"])

    if "project" in config:
        proj_cfg = config["project"]
        if "gcp_project" in proj_cfg:
            settings.project = proj_cfg["gcp_project"]
        if "location" in proj_cfg:
            settings.location = proj_cfg["location"]
