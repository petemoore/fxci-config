"""YAML configuration file loading utilities."""

from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def load_yaml(filename):
    """Load a YAML file from the config/ directory."""
    path = CONFIG_DIR / filename
    with open(path) as f:
        return yaml.safe_load(f)


def load_yaml_path(path):
    """Load a YAML file from an absolute path."""
    with open(path) as f:
        return yaml.safe_load(f)
