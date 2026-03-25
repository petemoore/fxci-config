"""Generate managed resource patterns from YAML."""

from .loader import load_yaml


def generate_managed():
    """Generate managed resource patterns from config/managed.yml."""
    return load_yaml("managed.yml")
