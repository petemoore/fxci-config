"""Generate hook and client JSON from projects/hooks/clients YAML."""

from .loader import load_yaml

DESCRIPTION_PREFIX = (
    "*DO NOT EDIT* - This resource is configured automatically by "
    "[ci-admin](https://github.com/mozilla-releng/fxci-config).\n\n"
)


def generate_hooks():
    """Generate hook resources from config/hooks.yml."""
    hooks_cfg = load_yaml("hooks.yml")
    result = []
    for key, h in hooks_cfg.items():
        hook = dict(h)
        # Ensure description has prefix
        desc = hook.get("description", "")
        if not desc.startswith("*DO NOT EDIT*"):
            hook["description"] = DESCRIPTION_PREFIX + desc
        result.append(hook)
    return result


def generate_clients():
    """Generate client resources from config/clients.yml."""
    clients_cfg = load_yaml("clients.yml")
    result = []
    for client_id, cfg in clients_cfg.items():
        client = {
            "clientId": client_id,
            "description": DESCRIPTION_PREFIX + cfg.get("description", ""),
            "scopes": cfg["scopes"],
        }
        result.append(client)
    return result
