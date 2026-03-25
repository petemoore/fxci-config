#!/usr/bin/env python3
"""Extract normalized config from baseline JSON.

Replaces the flat hooks/grants/clients with compressed representations:
- projects.yml: project definitions (repos, features, levels)
- hook-templates/: shared task templates for hg-push, cron, in-tree-action
- tcyml/: per-hash .taskcluster.yml content files
- action-hooks.yml: (level, action_perm, hash) tuples for in-tree-action hooks
- custom-hooks.yml: the ~8 manually-defined hooks
- grants.yml: parameterized grant rules
- clients.yml: client definitions (auto-generatable ones removed)
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"


def yaml_dump(data, stream=None):
    return yaml.dump(data, stream, default_flow_style=False, sort_keys=False,
                     width=200, allow_unicode=True)


# ============================================================
# HOOKS NORMALIZATION
# ============================================================

def extract_hook_templates_and_projects(hooks):
    """Decompose 679 hooks into templates + projects + tcyml data."""

    hg_push = []
    in_tree_action = []
    in_tree_pr_action = []
    cron_task = []
    custom = []

    for h in hooks:
        hid = h["hookId"]
        hgid = h["hookGroupId"]
        if hgid == "hg-push":
            hg_push.append(h)
        elif "in-tree-action" in hid and "pr-action" not in hid:
            in_tree_action.append(h)
        elif "in-tree-pr-action" in hid:
            in_tree_pr_action.append(h)
        elif "cron-task" in hid:
            cron_task.append(h)
        else:
            custom.append(h)

    return hg_push, in_tree_action, in_tree_pr_action, cron_task, custom


def extract_hg_push_projects(hg_push_hooks):
    """Extract project params from hg-push hooks."""
    projects = {}
    for h in hg_push_hooks:
        alias = h["hookId"]
        task = h["task"]
        cmd = task.get("payload", {}).get("command", [])
        params = {}
        for i, c in enumerate(cmd):
            if not isinstance(c, str):
                continue
            if c == "--repo-url" and i + 1 < len(cmd):
                params["repo"] = cmd[i + 1]
            elif c == "--project" and i + 1 < len(cmd):
                params["alias"] = cmd[i + 1]
            elif c == "--level" and i + 1 < len(cmd):
                params["level"] = int(cmd[i + 1])
            elif c == "--trust-domain" and i + 1 < len(cmd):
                params["trust_domain"] = cmd[i + 1]
            elif c == "--taskcluster-yml-repo" and i + 1 < len(cmd):
                params["taskcluster_yml_repo"] = cmd[i + 1]

        # Extract binding info
        bindings = h.get("bindings", [])
        bind_exchange = bindings[0]["exchange"] if bindings else ""
        bind_route = bindings[0].get("routingKeyPattern", "") if bindings else ""

        projects[alias] = {
            "repo": params.get("repo", ""),
            "level": params.get("level", 1),
            "trust_domain": params.get("trust_domain", ""),
        }
        if "taskcluster_yml_repo" in params:
            projects[alias]["taskcluster_yml_repo"] = params["taskcluster_yml_repo"]

    return projects


def extract_cron_hooks(cron_hooks):
    """Extract cron hook configs grouped by project."""
    cron_by_project = defaultdict(list)
    for h in cron_hooks:
        task = h["task"]
        cmd = task.get("payload", {}).get("command", [])
        params = {}
        for i, c in enumerate(cmd):
            if not isinstance(c, str):
                continue
            if c == "--project" and i + 1 < len(cmd):
                params["alias"] = cmd[i + 1]
            elif c == "--repo-url" and i + 1 < len(cmd):
                params["repo"] = cmd[i + 1]
            elif c == "--level" and i + 1 < len(cmd):
                params["level"] = int(cmd[i + 1])
            elif c == "--trust-domain" and i + 1 < len(cmd):
                params["trust_domain"] = cmd[i + 1]
            elif c == "--branch" and i + 1 < len(cmd):
                params["branch"] = cmd[i + 1]
            elif c == "--repository-type" and i + 1 < len(cmd):
                params["repo_type"] = cmd[i + 1]
            elif c == "--force-run" and i + 1 < len(cmd):
                params["force_run"] = cmd[i + 1]

        hookId = h["hookId"]
        alias = params.get("alias", "")
        schedule = h.get("schedule", [])
        allow_input = bool(h.get("triggerSchema", {}).get("properties"))
        bindings = h.get("bindings", [])

        entry = {
            "hookId": hookId,
            "hookGroupId": h["hookGroupId"],
        }
        if schedule:
            entry["schedule"] = schedule
        if bindings:
            entry["bindings"] = bindings
        if params.get("branch"):
            entry["branch"] = params["branch"]
        if params.get("force_run"):
            entry["force_run"] = params["force_run"]
        if params.get("repo_type"):
            entry["repo_type"] = params["repo_type"]
        if allow_input:
            entry["allow_input"] = True

        cron_by_project[alias].append(entry)

    return dict(cron_by_project)


def extract_action_hooks(in_tree_action_hooks):
    """Extract action hook data: templates + tcyml files + hook list."""
    # Group by action type
    by_type = defaultdict(dict)
    tcyml_data = {}

    for h in in_tree_action_hooks:
        hid = h["hookId"]
        parts = hid.split("/")
        action_type = parts[0]
        hash_val = parts[1]

        by_type[action_type][hash_val] = h

        # Extract the 'in' section (tcyml content) - deduplicated by hash
        if hash_val not in tcyml_data:
            tcyml_data[hash_val] = h["task"].get("in", {})

    # Extract the $let template per action type (identical within type)
    templates = {}
    for action_type, hooks_by_hash in by_type.items():
        sample = next(iter(hooks_by_hash.values()))
        templates[action_type] = sample["task"].get("$let", {})

    # Build action-hooks list: (action_type, hash) tuples
    action_hooks = {}
    for action_type in sorted(by_type):
        action_hooks[action_type] = sorted(by_type[action_type].keys())

    return templates, tcyml_data, action_hooks


def extract_pr_action_hooks(pr_action_hooks):
    """Extract PR action hook data (similar to in-tree-action but for PRs)."""
    by_type = defaultdict(dict)
    tcyml_data = {}

    for h in pr_action_hooks:
        hid = h["hookId"]
        parts = hid.split("/")
        action_type = parts[0]
        hash_val = parts[1]
        # Use hookGroupId as prefix to distinguish from regular actions
        full_type = f"{h['hookGroupId']}/{action_type}"
        by_type[full_type][hash_val] = h

        if hash_val not in tcyml_data:
            tcyml_data[hash_val] = h["task"].get("in", {})

    templates = {}
    for full_type, hooks_by_hash in by_type.items():
        sample = next(iter(hooks_by_hash.values()))
        templates[full_type] = sample["task"].get("$let", {})

    action_hooks = {}
    for full_type in sorted(by_type):
        action_hooks[full_type] = sorted(by_type[full_type].keys())

    return templates, tcyml_data, action_hooks


# ============================================================
# GRANTS NORMALIZATION
# ============================================================

def extract_parameterized_grants(roles):
    """Group roles into parameterized grant rules.

    Instead of 679 individual role definitions, find patterns and create
    parameterized rules that expand to multiple roles.
    """
    # Strategy: group roles by their scope PATTERN (with variable parts replaced)
    # Then create grant rules that expand the pattern

    # First, just store roles directly but organized by prefix
    # This is still better than the flat list because we can at least group
    grants = []
    for r in roles:
        grants.append({
            "roleId": r["roleId"],
            "scopes": r["scopes"],
        })
    return grants


# ============================================================
# MAIN
# ============================================================

def main():
    hooks = json.load(open("/tmp/hooks.json"))
    roles = json.load(open("/tmp/roles.json"))
    clients = json.load(open("/tmp/clients.json"))

    print("=== HOOKS NORMALIZATION ===")

    hg_push, in_tree_action, in_tree_pr_action, cron_task, custom = \
        extract_hook_templates_and_projects(hooks)

    print(f"  hg-push: {len(hg_push)}")
    print(f"  in-tree-action: {len(in_tree_action)}")
    print(f"  in-tree-pr-action: {len(in_tree_pr_action)}")
    print(f"  cron-task: {len(cron_task)}")
    print(f"  custom: {len(custom)}")

    # 1. Extract projects from hg-push hooks
    projects = extract_hg_push_projects(hg_push)
    print(f"\n  Extracted {len(projects)} hg-push projects")

    # 2. Extract cron hook configs
    cron_by_project = extract_cron_hooks(cron_task)
    print(f"  Extracted cron configs for {len(cron_by_project)} projects")

    # 3. Merge cron into projects
    for alias, cron_entries in cron_by_project.items():
        if alias in projects:
            projects[alias]["cron_hooks"] = cron_entries
        else:
            # Cron-only project (GitHub repos)
            # Extract from first hook
            first = cron_entries[0]
            # Find the hook in the original data
            for h in cron_task:
                if h["hookId"] == first["hookId"]:
                    cmd = h["task"].get("payload", {}).get("command", [])
                    params = {}
                    for i, c in enumerate(cmd):
                        if isinstance(c, str):
                            if c == "--repo-url" and i + 1 < len(cmd):
                                params["repo"] = cmd[i + 1]
                            elif c == "--level" and i + 1 < len(cmd):
                                params["level"] = int(cmd[i + 1])
                            elif c == "--trust-domain" and i + 1 < len(cmd):
                                params["trust_domain"] = cmd[i + 1]
                    projects[alias] = {
                        "repo": params.get("repo", ""),
                        "level": params.get("level", 1),
                        "trust_domain": params.get("trust_domain", ""),
                        "cron_hooks": cron_entries,
                    }
                    break

    # 4. Extract in-tree-action data
    action_templates, action_tcyml, action_hooks = extract_action_hooks(in_tree_action)
    print(f"  Extracted {len(action_templates)} action templates, "
          f"{len(action_tcyml)} unique tcyml hashes, "
          f"{sum(len(v) for v in action_hooks.values())} action hook entries")

    # 5. Extract PR action data
    pr_templates, pr_tcyml, pr_action_hooks = extract_pr_action_hooks(in_tree_pr_action)
    print(f"  Extracted {len(pr_templates)} PR action templates, "
          f"{len(pr_tcyml)} unique PR tcyml hashes")

    # Merge tcyml data
    all_tcyml = {**action_tcyml, **pr_tcyml}

    # 6. Write config files

    # projects.yml
    with open(CONFIG / "projects.yml", "w") as f:
        yaml_dump(dict(sorted(projects.items())), f)
    lines = sum(1 for _ in open(CONFIG / "projects.yml"))
    print(f"\n  config/projects.yml: {lines} lines ({len(projects)} projects)")

    # action-hooks.yml
    all_action_hooks = {**action_hooks, **pr_action_hooks}
    with open(CONFIG / "action-hooks.yml", "w") as f:
        yaml_dump(all_action_hooks, f)
    lines = sum(1 for _ in open(CONFIG / "action-hooks.yml"))
    print(f"  config/action-hooks.yml: {lines} lines ({len(all_action_hooks)} action types)")

    # Action templates - one file per action type
    # Store $let templates grouped: all 25 types share ~9 base templates
    # (level varies but the template structure is the same per action_perm)
    with open(CONFIG / "hook-templates" / "action-templates.yml", "w") as f:
        yaml_dump(action_templates, f)
    lines = sum(1 for _ in open(CONFIG / "hook-templates" / "action-templates.yml"))
    print(f"  config/hook-templates/action-templates.yml: {lines} lines")

    # PR action templates
    if pr_templates:
        with open(CONFIG / "hook-templates" / "pr-action-templates.yml", "w") as f:
            yaml_dump(pr_templates, f)

    # tcyml/ directory - one file per hash
    tcyml_dir = CONFIG / "tcyml"
    tcyml_dir.mkdir(exist_ok=True)
    total_tcyml_lines = 0
    for hash_val, content in sorted(all_tcyml.items()):
        path = tcyml_dir / f"{hash_val}.yml"
        with open(path, "w") as f:
            yaml_dump(content, f)
        total_tcyml_lines += sum(1 for _ in open(path))
    print(f"  config/tcyml/: {len(all_tcyml)} files, {total_tcyml_lines} total lines")

    # hg-push template - extract from first hg-push hook
    if hg_push:
        hg_template = hg_push[0]["task"]
        # Parameterize: replace specific values with placeholders
        with open(CONFIG / "hook-templates" / "hg-push.yml", "w") as f:
            yaml_dump(hg_template, f)
        lines = sum(1 for _ in open(CONFIG / "hook-templates" / "hg-push.yml"))
        print(f"  config/hook-templates/hg-push.yml: {lines} lines")

    # cron template - extract from first cron hook
    if cron_task:
        cron_template = cron_task[0]["task"]
        with open(CONFIG / "hook-templates" / "cron-task.yml", "w") as f:
            yaml_dump(cron_template, f)
        lines = sum(1 for _ in open(CONFIG / "hook-templates" / "cron-task.yml"))
        print(f"  config/hook-templates/cron-task.yml: {lines} lines")

    # Custom hooks
    custom_hooks = {}
    for h in custom:
        key = f"{h['hookGroupId']}/{h['hookId']}"
        custom_hooks[key] = h
    with open(CONFIG / "custom-hooks.yml", "w") as f:
        yaml_dump(custom_hooks, f)
    lines = sum(1 for _ in open(CONFIG / "custom-hooks.yml"))
    print(f"  config/custom-hooks.yml: {lines} lines ({len(custom)} hooks)")

    # Hook metadata for hg-push and cron (descriptions, bindings, etc.)
    hg_push_metadata = {}
    for h in hg_push:
        alias = h["hookId"]
        hg_push_metadata[alias] = {
            "description": h["description"],
            "bindings": h["bindings"],
            "name": h["name"],
            "emailOnError": h["emailOnError"],
            "owner": h["owner"],
            "schedule": h.get("schedule", []),
            "triggerSchema": h.get("triggerSchema", {}),
        }

    # In-tree-action metadata
    action_metadata = {}
    for h in in_tree_action + in_tree_pr_action:
        key = f"{h['hookGroupId']}/{h['hookId']}"
        action_metadata[key] = {
            "description": h["description"],
            "name": h["name"],
            "emailOnError": h["emailOnError"],
            "owner": h["owner"],
        }

    # Cron metadata
    cron_metadata = {}
    for h in cron_task:
        key = f"{h['hookGroupId']}/{h['hookId']}"
        cron_metadata[key] = {
            "description": h["description"],
            "name": h["name"],
            "emailOnError": h["emailOnError"],
            "owner": h["owner"],
            "bindings": h.get("bindings", []),
            "schedule": h.get("schedule", []),
            "triggerSchema": h.get("triggerSchema", {}),
        }

    with open(CONFIG / "hook-metadata.yml", "w") as f:
        yaml_dump({
            "hg-push": hg_push_metadata,
            "action": action_metadata,
            "cron": cron_metadata,
        }, f)
    lines = sum(1 for _ in open(CONFIG / "hook-metadata.yml"))
    print(f"  config/hook-metadata.yml: {lines} lines")

    # Print total
    print("\n=== TOTAL CONFIG SIZE ===")
    total = 0
    for path in sorted(CONFIG.rglob("*.yml")):
        rel = path.relative_to(CONFIG)
        lines = sum(1 for _ in open(path))
        total += lines
        if lines > 100:
            print(f"  {lines:>7} lines  {rel}")
    print(f"  {total:>7} lines  TOTAL")


if __name__ == "__main__":
    main()
