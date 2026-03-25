"""Generate hook JSON from normalized config.

Sources:
- config/action-hooks.yml (manifest) + tcyml cache → in-tree-action hooks
- config/action-trigger-schemas.yml → trigger schema
- config/historical-hooks.yml → list of historical hook IDs
- config/hg-push-hooks.yml → hg-push hooks
- config/cron-hooks.yml → cron hooks
- config/custom-hooks.yml → custom hooks

Descriptions for action hooks are derived from the tcyml cache (hash → project/branch mapping).
The tcyml .taskcluster.yml content is fetched from repos and cached in output/tcyml_cache/.
"""

import json
import re
from collections import defaultdict
from pathlib import Path

from .loader import CONFIG_DIR, load_yaml, load_yaml_path

DESCRIPTION_PREFIX = (
    "*DO NOT EDIT* - This resource is configured automatically by "
    "[ci-admin](https://github.com/mozilla-releng/fxci-config).\n\n"
)

# Global tcyml cache (loaded once)
_tcyml_cache = None
_hash_to_projects = None


def _get_tcyml_cache():
    """Load the tcyml cache and build hash→projects mapping."""
    global _tcyml_cache, _hash_to_projects
    if _tcyml_cache is not None:
        return _tcyml_cache, _hash_to_projects

    cache_dir = CONFIG_DIR.parent / "output" / "tcyml_cache"
    cache_file = cache_dir / "tcyml_cache.json"
    _tcyml_cache = {}
    _hash_to_projects = defaultdict(list)

    if cache_file.exists():
        raw = json.loads(cache_file.read_text())
        for key, entry in raw.items():
            if not entry or not entry.get("hash"):
                continue
            h = entry["hash"]
            _tcyml_cache[h] = entry
            # Derive project/branch from cache key (repo_url@branch)
            if key.startswith("__static__/"):
                continue  # synthetic entries have no project info
            if "@" in key:
                repo_url, branch = key.rsplit("@", 1)
                # Look up alias from projects.yml
                projects = load_yaml("projects.yml")
                for alias, proj in projects.items():
                    if proj.get("repo", "").rstrip("/") == repo_url.rstrip("/"):
                        _hash_to_projects[h].append((alias, branch))

    return _tcyml_cache, _hash_to_projects


def _load_tcyml(hash_val):
    """Load tcyml content for a hash from cache."""
    cache, _ = _get_tcyml_cache()
    entry = cache.get(hash_val)
    if entry:
        parsed = entry.get("parsed", {})
        if isinstance(parsed.get("tasks"), list):
            return parsed["tasks"][0]
        return parsed
    return {}


def _build_description(action_perm, level, hash_val, is_historical=False, is_pr=False):
    """Build the description for an action hook from cache data."""
    _, hash_to_projects = _get_tcyml_cache()
    matching = []
    for alias, branch in sorted(hash_to_projects.get(hash_val, [])):
        matching.append(f"{alias}, branch: '{branch}'")

    desc = (
        f"{'PR a' if is_pr else 'A'}ction task {action_perm} at level {level}, "
        f"with `.taskcluster.yml` hash {hash_val}.\n\n"
        f"For (project, branch) combinations:\n"
        f"{chr(10).join(matching)}\n\n"
        f"This hook is fired in response to actions defined in a\n"
        f"Gecko decision task's `actions.json`.\n"
    )
    if is_historical:
        desc += (
            "\n\nThis hook is no longer current and is kept for "
            "historical purposes."
        )
    return desc


def generate_action_hooks():
    """Generate in-tree-action hooks from manifest + tcyml cache.

    Uses action-hooks.yml as the manifest, derives descriptions from
    the tcyml cache, and loads tcyml content for each hash.
    """
    action_hooks_cfg = load_yaml("action-hooks.yml")
    templates = load_yaml("hook-templates/action-templates.yml")
    trigger_schemas = load_yaml("action-trigger-schemas.yml") or {}
    default_schema = trigger_schemas.get("default", {})
    historical = set(load_yaml("historical-hooks.yml") or [])

    hooks = []
    for hook_group_id, hook_ids in action_hooks_cfg.items():
        schema = trigger_schemas.get(hook_group_id, default_schema)

        for hook_id in hook_ids:
            action_type, hash_val = hook_id.split("/")
            template = templates.get(action_type, {})
            tcyml_content = _load_tcyml(hash_val)

            task = {"$let": template, "in": tcyml_content}

            # Parse level and perm from action_type
            m = re.match(r"in-tree-(?:pr-)?action-(\d+)-(.+)", action_type)
            level = m.group(1) if m else "?"
            perm = m.group(2) if m else action_type
            is_pr = "pr-action" in action_type

            full_id = f"{hook_group_id}/{hook_id}"
            is_hist = full_id in historical
            desc_body = _build_description(perm, level, hash_val, is_hist, is_pr)

            hook = {
                "bindings": [],
                "description": DESCRIPTION_PREFIX + desc_body,
                "emailOnError": True,
                "hookGroupId": hook_group_id,
                "hookId": hook_id,
                "name": f"{hook_group_id}/{hook_id}",
                "owner": "taskcluster-notifications@mozilla.com",
                "schedule": [],
                "task": task,
                "triggerSchema": schema,
            }
            hooks.append(hook)

    return hooks


def generate_hg_push_hooks():
    """Generate hg-push hooks from hg-push-hooks.yml."""
    data = load_yaml("hg-push-hooks.yml")
    hooks = []
    for alias, cfg in data.items():
        hook = {
            "bindings": cfg["bindings"],
            "description": DESCRIPTION_PREFIX + cfg["description"],
            "emailOnError": False,
            "hookGroupId": "hg-push",
            "hookId": alias,
            "name": f"hg-push/{alias}",
            "owner": "release+tc-hooks@mozilla.com",
            "schedule": [],
            "task": cfg["task"],
            "triggerSchema": cfg["triggerSchema"],
        }
        hooks.append(hook)
    return hooks


def generate_cron_hooks():
    """Generate cron hooks from cron-hooks.yml."""
    data = load_yaml("cron-hooks.yml")
    hooks = []
    for key, cfg in data.items():
        hook_group_id, hook_id = key.split("/", 1)
        hook = {
            "bindings": cfg.get("bindings", []),
            "description": DESCRIPTION_PREFIX + cfg["description"],
            "emailOnError": True,
            "hookGroupId": hook_group_id,
            "hookId": hook_id,
            "name": f"{hook_group_id}/{hook_id}",
            "owner": "release+tc-hooks@mozilla.com",
            "schedule": cfg.get("schedule", []),
            "task": cfg["task"],
            "triggerSchema": cfg["triggerSchema"],
        }
        hooks.append(hook)
    return hooks


def generate_custom_hooks():
    """Generate custom hooks from custom-hooks.yml."""
    data = load_yaml("custom-hooks.yml")
    return list(data.values())


def generate_hooks(**kwargs):
    """Generate all hooks."""
    hooks = []
    hooks.extend(generate_hg_push_hooks())
    hooks.extend(generate_action_hooks())
    hooks.extend(generate_cron_hooks())
    hooks.extend(generate_custom_hooks())
    return hooks
