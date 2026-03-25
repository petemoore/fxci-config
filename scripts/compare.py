#!/usr/bin/env python3
"""Compare generated output/ against baseline/ JSON files.

Reports per-file: matching, missing, extra, and differing resources.
Exit code 0 = perfect match, 1 = differences found.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "baseline"
OUTPUT = ROOT / "output"

# Map each file to the function that extracts a unique key from a resource.
# managed.json is a flat list of strings, so the key IS the string.
KEY_EXTRACTORS = {
    "workerpools.json": lambda r: r["workerPoolId"],
    "roles.json": lambda r: r["roleId"],
    "clients.json": lambda r: r["clientId"],
    "hooks.json": lambda r: f"{r['hookGroupId']}/{r['hookId']}",
    "managed.json": lambda r: r,  # strings
}


def deep_sort(obj):
    """Recursively sort dicts by key and lists for deterministic comparison."""
    if isinstance(obj, dict):
        return {k: deep_sort(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        sorted_items = [deep_sort(i) for i in obj]
        # Sort lists of comparable items; leave mixed/nested lists as-is
        try:
            return sorted(sorted_items, key=lambda x: json.dumps(x, sort_keys=True))
        except TypeError:
            return sorted_items
    return obj


def compare_file(name):
    baseline_path = BASELINE / name
    output_path = OUTPUT / name

    if not baseline_path.exists():
        print(f"  SKIP {name}: no baseline file")
        return True

    if not output_path.exists():
        baseline_data = json.loads(baseline_path.read_text())
        n = len(baseline_data)
        print(f"  MISS {name}: output missing ({n} baseline resources)")
        return False

    baseline_data = json.loads(baseline_path.read_text())
    output_data = json.loads(output_path.read_text())

    key_fn = KEY_EXTRACTORS[name]

    baseline_map = {key_fn(r): r for r in baseline_data}
    output_map = {key_fn(r): r for r in output_data}

    baseline_keys = set(baseline_map)
    output_keys = set(output_map)

    missing = sorted(baseline_keys - output_keys)
    extra = sorted(output_keys - baseline_keys)
    common = baseline_keys & output_keys

    matching = 0
    differing = []
    for key in sorted(common):
        b = deep_sort(baseline_map[key])
        o = deep_sort(output_map[key])
        if b == o:
            matching += 1
        else:
            differing.append(key)

    total = len(baseline_keys)
    ok = not missing and not extra and not differing

    status = "OK  " if ok else "DIFF"
    print(f"  {status} {name}: {matching}/{total} match", end="")
    parts = []
    if missing:
        parts.append(f"{len(missing)} missing")
    if extra:
        parts.append(f"{len(extra)} extra")
    if differing:
        parts.append(f"{len(differing)} differ")
    if parts:
        print(f" ({', '.join(parts)})")
    else:
        print()

    # Show details for first few differences
    if differing and "--verbose" in sys.argv:
        for key in differing[:5]:
            print(f"\n    --- {key} ---")
            b = json.dumps(deep_sort(baseline_map[key]), indent=2, sort_keys=True)
            o = json.dumps(deep_sort(output_map[key]), indent=2, sort_keys=True)
            b_lines = b.splitlines()
            o_lines = o.splitlines()
            for i, (bl, ol) in enumerate(zip(b_lines, o_lines)):
                if bl != ol:
                    print(f"    baseline L{i+1}: {bl.strip()}")
                    print(f"    output   L{i+1}: {ol.strip()}")
            if len(b_lines) != len(o_lines):
                print(f"    (baseline {len(b_lines)} lines vs output {len(o_lines)} lines)")
        if len(differing) > 5:
            print(f"    ... and {len(differing) - 5} more")

    if missing and "--verbose" in sys.argv:
        for key in missing[:10]:
            print(f"    MISSING: {key}")
        if len(missing) > 10:
            print(f"    ... and {len(missing) - 10} more missing")

    if extra and "--verbose" in sys.argv:
        for key in extra[:10]:
            print(f"    EXTRA: {key}")
        if len(extra) > 10:
            print(f"    ... and {len(extra) - 10} more extra")

    return ok


def main():
    print("Comparing output/ vs baseline/:")
    all_ok = True
    for name in KEY_EXTRACTORS:
        if not compare_file(name):
            all_ok = False

    if all_ok:
        print("\nAll files match baseline.")
    else:
        print("\nDifferences found.")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
