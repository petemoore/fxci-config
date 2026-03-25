"""Generate role JSON from grants YAML."""

from .loader import load_yaml

DESCRIPTION_PREFIX = (
    "*DO NOT EDIT* - This resource is configured automatically by "
    "[ci-admin](https://github.com/mozilla-releng/fxci-config).\n\n"
)


def generate_roles():
    """Generate role resources from config/grants.yml."""
    grants = load_yaml("grants.yml")
    result = []
    for g in grants:
        desc = g.get("description", "")
        role = {
            "description": DESCRIPTION_PREFIX + desc,
            "roleId": g["roleId"],
            "scopes": g["scopes"],
        }
        result.append(role)
    return result
