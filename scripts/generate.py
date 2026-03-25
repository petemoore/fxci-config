#!/usr/bin/env python3
"""Generate Taskcluster resource JSON from config YAML.

Reads config/ YAML files and writes output/ JSON files.
"""

import json
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUTPUT = ROOT / "output"


def write_json(filename, data):
    """Write sorted JSON to output directory."""
    OUTPUT.mkdir(exist_ok=True)
    path = OUTPUT / filename
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    return len(data)


def main():
    from generate.worker_pools import generate_worker_pools

    print("Generating resources...")

    n = write_json("workerpools.json", generate_worker_pools())
    print(f"  workerpools.json: {n} pools")

    # Placeholder for other generators
    from generate.grants import generate_roles
    n = write_json("roles.json", generate_roles())
    print(f"  roles.json: {n} roles")

    from generate.hooks import generate_hooks
    n = write_json("hooks.json", generate_hooks())
    print(f"  hooks.json: {n} hooks")

    from generate.projects import generate_clients
    n = write_json("clients.json", generate_clients())
    print(f"  clients.json: {n} clients")

    from generate.managed import generate_managed
    n = write_json("managed.json", generate_managed())
    print(f"  managed.json: {n} patterns")

    print("\nDone.")


if __name__ == "__main__":
    main()
