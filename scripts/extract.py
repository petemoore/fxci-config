#!/usr/bin/env python3
"""Extract config YAML from baseline JSON files.

Produces:
  config/imagesets.yml      - Image definitions
  config/worker-pools.yml   - Flat pool definitions
  config/grants.yml         - Role/grant definitions
  config/hooks.yml          - Hook definitions
  config/clients.yml        - Client definitions
  config/managed.yml        - Managed resource patterns
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "baseline"
CONFIG = ROOT / "config"


# ---------- YAML formatting helpers ----------

class LiteralStr(str):
    """String that should be rendered as a YAML literal block."""
    pass


def literal_str_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(LiteralStr, literal_str_representer)


def yaml_dump(data, stream=None):
    return yaml.dump(
        data,
        stream,
        default_flow_style=False,
        sort_keys=False,
        width=200,
        allow_unicode=True,
    )


# ---------- Imageset extraction ----------

def extract_gcp_image(lc):
    """Extract sourceImage from a GCP launchConfig."""
    for disk in lc.get("disks", []):
        si = disk.get("initializeParams", {}).get("sourceImage", "")
        if si:
            return si
    return ""


def extract_azure_image(lc):
    """Extract image reference from an Azure launchConfig."""
    return lc.get("storageProfile", {}).get("imageReference", {}).get("id", "")


def imageset_name_from_gcp(image_path):
    """Derive imageset name from GCP image path."""
    # projects/xxx/global/images/<name>
    name = image_path.split("/")[-1]
    return name


SUB_LABELS = {
    "108d46d5-fe9b-4850-9a7d-8c914aa6c1f0": "l1",
    "a30e97ab-734a-4f3b-a0e4-c51c0bff0701": "l3",
}


def imageset_name_from_azure(image_id):
    """Derive imageset name from Azure image reference.

    Azure images have location embedded, e.g.:
      .../images/win2012r2-64-l1-centralus-2012-R2-Datacenter-75bd9ed
      .../galleries/win11_a64_24h2_tester/images/win11_a64_24h2_tester/versions/1.0.0
    We need a location-independent name that preserves the hash/version suffix.
    For gallery images, the subscription label is appended to distinguish
    same gallery across providers.
    """
    if "/galleries/" in image_id:
        # Gallery image: .../galleries/<gallery>/images/<image>/versions/<ver>
        m = re.search(r"/galleries/([^/]+)/images/([^/]+)/versions/([^/]+)", image_id)
        sub_match = re.search(r"/subscriptions/([^/]+)/", image_id)
        sub_id = sub_match.group(1) if sub_match else "unknown"
        sub_label = SUB_LABELS.get(sub_id, sub_id[:8])
        if m:
            return f"gallery-{m.group(1)}-{sub_label}"
    else:
        # Standard image: .../images/<base>-<location>-<sku>-<hash>
        img_name = image_id.split("/images/")[-1]
        locations = [
            "centralus", "northcentralus", "eastus", "eastus2",
            "westus", "westus2", "westus3", "northeurope", "uksouth",
            "ukwest", "canadacentral", "centralindia", "southindia",
        ]
        for loc in sorted(locations, key=len, reverse=True):
            if f"-{loc}-" in img_name:
                # Split on first occurrence of location
                prefix, suffix = img_name.split(f"-{loc}-", 1)
                # suffix is like "2022-datacenter-azure-edition-8346140"
                # or "win11-22h2-avd-db0c108"
                # Include the suffix hash to distinguish alpha vs production
                return f"{prefix}-{suffix}"
        # Fallback
        return img_name

    return image_id.split("/")[-1]


def extract_imagesets():
    """Extract imagesets from baseline worker pools."""
    pools = json.load(open(BASELINE / "workerpools.json"))

    gcp_images = {}  # image_path -> imageset_name
    azure_images = {}  # base_name -> {location: full_image_id}
    azure_gallery_images = {}  # gallery_name -> {location: full_image_id}

    # First pass: collect all images
    for p in pools:
        provider = p["providerId"]
        for lc in p["config"].get("launchConfigs", []):
            if "machineType" in lc:  # GCP
                img = extract_gcp_image(lc)
                if img and img not in gcp_images:
                    gcp_images[img] = imageset_name_from_gcp(img)
            elif "hardwareProfile" in lc:  # Azure
                img_id = extract_azure_image(lc)
                if img_id:
                    base = imageset_name_from_azure(img_id)
                    loc = lc.get("location", "unknown")
                    if "/galleries/" in img_id:
                        # base already includes subscription label from imageset_name_from_azure
                        azure_gallery_images.setdefault(base, {})[loc] = img_id
                    else:
                        azure_images.setdefault(base, {})[loc] = img_id

    imagesets = {}

    # GCP imagesets
    for img_path, name in sorted(gcp_images.items(), key=lambda x: x[1]):
        imagesets[name] = {
            "cloud": "gcp",
            "gcp": {"image": img_path},
        }

    # Azure imagesets (standard)
    for base_name, loc_map in sorted(azure_images.items()):
        imagesets[base_name] = {
            "cloud": "azure",
            "azure": {
                "type": "image",
                "images": dict(sorted(loc_map.items())),
            },
        }

    # Azure gallery imagesets
    for gallery_name, loc_map in sorted(azure_gallery_images.items()):
        imagesets[gallery_name] = {
            "cloud": "azure",
            "azure": {
                "type": "gallery",
                "images": dict(sorted(loc_map.items())),
            },
        }

    return imagesets


# ---------- Worker pool extraction ----------

def extract_zone(machineType_path):
    """Extract zone from zones/<zone>/machineTypes/<type>."""
    m = re.match(r"zones/([^/]+)/machineTypes/(.+)", machineType_path)
    if m:
        return m.group(1), m.group(2)
    return None, machineType_path


def normalize_gcp_disk(disk, zone):
    """Remove zone prefix from disk config."""
    d = dict(disk)
    ip = dict(d.get("initializeParams", {}))
    # Remove sourceImage (handled by imageset)
    ip.pop("sourceImage", None)
    # Normalize diskType: zones/<zone>/diskTypes/<type> -> <type>
    dt = ip.get("diskType", "")
    if dt.startswith("zones/"):
        ip["diskType"] = dt.split("/diskTypes/")[-1]
    if ip:
        d["initializeParams"] = ip
    else:
        d.pop("initializeParams", None)
    return d


def extract_gcp_pool(pool):
    """Extract compact config from a GCP pool."""
    config = pool["config"]
    lcs = config["launchConfigs"]

    # All launchConfigs share the same base config, differ by zone
    zones = []
    machine_type = None
    for lc in lcs:
        zone, mt = extract_zone(lc.get("machineType", ""))
        if zone:
            zones.append(zone)
        if machine_type is None:
            machine_type = mt

    # Get representative launchConfig (first one)
    rep = lcs[0]
    first_zone = zones[0] if zones else "unknown"

    # Extract imageset
    image = extract_gcp_image(rep)
    imageset = imageset_name_from_gcp(image) if image else None

    # Normalize disks
    disks = [normalize_gcp_disk(d, first_zone) for d in rep.get("disks", [])]

    # Preserve original zone ordering (deduplicated)
    seen = set()
    ordered_zones = []
    for z in zones:
        if z not in seen:
            seen.add(z)
            ordered_zones.append(z)

    result = {
        "providerId": pool["providerId"],
        "description": strip_do_not_edit(pool["description"]),
        "owner": pool["owner"],
        "emailOnError": pool["emailOnError"],
        "cloud": "gcp",
        "imageset": imageset,
        "zones": ordered_zones,
        "machineType": machine_type,
        "minCapacity": config.get("minCapacity", 0),
        "maxCapacity": config.get("maxCapacity", 0),
    }

    # Optional fields from launchConfig
    if rep.get("minCpuPlatform"):
        result["minCpuPlatform"] = rep["minCpuPlatform"]

    if disks:
        result["disks"] = disks

    if rep.get("scheduling"):
        result["scheduling"] = rep["scheduling"]

    if rep.get("networkInterfaces"):
        nic = rep["networkInterfaces"][0]
        ac = nic.get("accessConfigs", [])
        if ac and ac != [{"type": "ONE_TO_ONE_NAT"}]:
            result["networkInterfaces"] = rep["networkInterfaces"]
        # else: default, no need to store

    if rep.get("advancedMachineFeatures"):
        result["advancedMachineFeatures"] = rep["advancedMachineFeatures"]

    if rep.get("guestAccelerators"):
        # Normalize zone-specific accelerator types
        gas = []
        for ga in rep["guestAccelerators"]:
            ga = dict(ga)
            at = ga.get("acceleratorType", "")
            if at.startswith("zones/"):
                # zones/<zone>/acceleratorTypes/<type> -> <type>
                ga["acceleratorType"] = at.split("/acceleratorTypes/")[-1]
            gas.append(ga)
        result["guestAccelerators"] = gas

    if rep.get("workerConfig"):
        result["workerConfig"] = rep["workerConfig"]

    if rep.get("capacityPerInstance", 1) != 1:
        result["capacityPerInstance"] = rep["capacityPerInstance"]

    if config.get("lifecycle"):
        result["lifecycle"] = config["lifecycle"]

    return result


def strip_do_not_edit(desc):
    """Strip the auto-generated prefix from descriptions."""
    prefix = "*DO NOT EDIT* - This resource is configured automatically by [ci-admin](https://github.com/mozilla-releng/fxci-config).\n\n"
    if desc.startswith(prefix):
        return desc[len(prefix):]
    return desc


def extract_azure_pool(pool):
    """Extract compact config from an Azure pool."""
    config = pool["config"]
    lcs = config["launchConfigs"]

    locations = []
    vm_size = None
    for lc in lcs:
        loc = lc.get("location", "unknown")
        if loc not in locations:
            locations.append(loc)
        if vm_size is None:
            vm_size = lc.get("hardwareProfile", {}).get("vmSize")

    rep = lcs[0]

    # Extract imageset
    img_id = extract_azure_image(rep)
    imageset = imageset_name_from_azure(img_id) if img_id else None

    # Determine subnet group override
    pool_group = pool["workerPoolId"].split("/")[0]
    actual_sub = rep.get("subnetId", "")
    subnet_group = None
    if actual_sub:
        # Extract subnet group from actual subnetId
        loc0 = locations[0]
        slug = {
            "canadacentral": "canada-central", "centralindia": "central-india",
            "centralus": "central-us", "eastus": "east-us", "eastus2": "east-us-2",
            "northcentralus": "north-central-us", "northeurope": "north-europe",
            "southindia": "south-india", "uksouth": "uk-south", "ukwest": "uk-west",
            "westus": "west-us", "westus2": "west-us-2", "westus3": "west-us-3",
        }.get(loc0, loc0)
        # Pattern: rg-<slug>-<subnetGroup>/...
        import re as _re
        m = _re.search(rf"rg-{_re.escape(slug)}-([^/]+)/", actual_sub)
        if m and m.group(1) != pool_group:
            subnet_group = m.group(1)

    result = {
        "providerId": pool["providerId"],
        "description": strip_do_not_edit(pool["description"]),
        "owner": pool["owner"],
        "emailOnError": pool["emailOnError"],
        "cloud": "azure",
        "imageset": imageset,
        "locations": locations,  # preserve original ordering
        "vmSize": vm_size,
        "minCapacity": config.get("minCapacity", 0),
        "maxCapacity": config.get("maxCapacity", 0),
    }

    if subnet_group:
        result["subnetGroup"] = subnet_group

    if rep.get("priority"):
        result["priority"] = rep["priority"]

    if rep.get("billingProfile"):
        result["billingProfile"] = rep["billingProfile"]

    if rep.get("evictionPolicy"):
        result["evictionPolicy"] = rep["evictionPolicy"]

    if rep.get("osProfile"):
        result["osProfile"] = rep["osProfile"]

    if rep.get("diagnosticsProfile"):
        result["diagnosticsProfile"] = rep["diagnosticsProfile"]

    # Data disks
    data_disks = rep.get("storageProfile", {}).get("dataDisks", [])
    if data_disks:
        result["dataDisks"] = data_disks

    os_disk = rep.get("storageProfile", {}).get("osDisk", {})
    if os_disk:
        result["osDisk"] = os_disk

    if rep.get("tags"):
        result["tags"] = rep["tags"]

    if rep.get("subnetId"):
        # Extract the subnet pattern (location-independent)
        # subnetId has location embedded, but we'll store the full pattern
        # and resolve per-location in generator
        pass  # Handled by locations + environment config

    if rep.get("workerConfig"):
        result["workerConfig"] = rep["workerConfig"]

    if rep.get("capacityPerInstance", 1) != 1:
        result["capacityPerInstance"] = rep["capacityPerInstance"]

    if config.get("lifecycle"):
        result["lifecycle"] = config["lifecycle"]

    return result


def extract_worker_pools():
    """Extract all worker pool definitions."""
    pools = json.load(open(BASELINE / "workerpools.json"))
    result = {}

    for p in pools:
        pid = p["workerPoolId"]
        provider = p["providerId"]

        if provider in ("fxci-level1-gcp", "fxci-level3-gcp"):
            result[pid] = extract_gcp_pool(p)
        elif provider in ("azure2", "azure_trusted"):
            result[pid] = extract_azure_pool(p)
        else:
            print(f"  WARNING: unknown provider {provider} for {pid}", file=sys.stderr)
            result[pid] = {
                "providerId": provider,
                "description": strip_do_not_edit(p["description"]),
                "owner": p["owner"],
                "emailOnError": p["emailOnError"],
                "config": p["config"],
            }

    return result


# ---------- Grants extraction ----------

def extract_grants():
    """Extract grants from baseline roles."""
    roles = json.load(open(BASELINE / "roles.json"))
    result = []
    for r in roles:
        entry = {
            "roleId": r["roleId"],
            "scopes": r["scopes"],
        }
        desc = strip_do_not_edit(r["description"])
        if desc:
            entry["description"] = desc
        result.append(entry)
    return result


# ---------- Hooks extraction ----------

def extract_hooks():
    """Extract hooks from baseline."""
    hooks = json.load(open(BASELINE / "hooks.json"))
    result = {}
    for h in hooks:
        key = f"{h['hookGroupId']}/{h['hookId']}"
        entry = {}
        for field in ["hookGroupId", "hookId", "bindings", "description",
                       "emailOnError", "name", "owner",
                       "schedule", "task", "triggerSchema"]:
            if field in h:
                val = h[field]
                desc_val = val
                if field == "description":
                    desc_val = strip_do_not_edit(val)
                    entry[field] = desc_val
                else:
                    entry[field] = val
        result[key] = entry
    return result


# ---------- Clients extraction ----------

def extract_clients():
    """Extract clients from baseline."""
    clients = json.load(open(BASELINE / "clients.json"))
    result = {}
    for c in clients:
        cid = c["clientId"]
        entry = {
            "scopes": c["scopes"],
        }
        desc = strip_do_not_edit(c["description"])
        if desc:
            entry["description"] = desc
        result[cid] = entry
    return result


# ---------- Managed extraction ----------

def extract_managed():
    """Extract managed patterns from baseline."""
    return json.load(open(BASELINE / "managed.json"))


# ---------- Main ----------

def main():
    CONFIG.mkdir(exist_ok=True)

    print("Extracting imagesets...")
    imagesets = extract_imagesets()
    with open(CONFIG / "imagesets.yml", "w") as f:
        yaml_dump(imagesets, f)
    print(f"  {len(imagesets)} imagesets -> config/imagesets.yml")

    print("Extracting worker pools...")
    pools = extract_worker_pools()
    with open(CONFIG / "worker-pools.yml", "w") as f:
        yaml_dump(pools, f)
    print(f"  {len(pools)} pools -> config/worker-pools.yml")

    print("Extracting grants (roles)...")
    grants = extract_grants()
    with open(CONFIG / "grants.yml", "w") as f:
        yaml_dump(grants, f)
    print(f"  {len(grants)} grants -> config/grants.yml")

    print("Extracting hooks...")
    hooks = extract_hooks()
    with open(CONFIG / "hooks.yml", "w") as f:
        yaml_dump(hooks, f)
    print(f"  {len(hooks)} hooks -> config/hooks.yml")

    print("Extracting clients...")
    clients = extract_clients()
    with open(CONFIG / "clients.yml", "w") as f:
        yaml_dump(clients, f)
    print(f"  {len(clients)} clients -> config/clients.yml")

    print("Extracting managed patterns...")
    managed = extract_managed()
    with open(CONFIG / "managed.yml", "w") as f:
        yaml_dump(managed, f)
    print(f"  {len(managed)} patterns -> config/managed.yml")

    print("\nDone.")


if __name__ == "__main__":
    main()
