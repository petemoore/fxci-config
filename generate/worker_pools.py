"""Generate worker pool JSON from flat YAML definitions."""

from .imagesets import resolve_azure_images, resolve_gcp_image
from .loader import load_yaml

DESCRIPTION_PREFIX = (
    "*DO NOT EDIT* - This resource is configured automatically by "
    "[ci-admin](https://github.com/mozilla-releng/fxci-config).\n\n"
)

# Azure subscription IDs by provider
AZURE_SUBSCRIPTIONS = {
    "azure2": "108d46d5-fe9b-4850-9a7d-8c914aa6c1f0",
    "azure_trusted": "a30e97ab-734a-4f3b-a0e4-c51c0bff0701",
}

# Azure location -> slug for subnet derivation
LOCATION_SLUGS = {
    "canadacentral": "canada-central",
    "centralindia": "central-india",
    "centralus": "central-us",
    "eastus": "east-us",
    "eastus2": "east-us-2",
    "northcentralus": "north-central-us",
    "northeurope": "north-europe",
    "southindia": "south-india",
    "uksouth": "uk-south",
    "ukwest": "uk-west",
    "westus": "west-us",
    "westus2": "west-us-2",
    "westus3": "west-us-3",
}


def azure_subnet_id(provider_id, pool_id, location):
    """Derive Azure subnetId from pool ID and location."""
    pool_group = pool_id.split("/")[0]
    # Some pools override the subnet group name
    # (e.g., mozillavpn-1 uses vpn-1)
    sub_id = AZURE_SUBSCRIPTIONS[provider_id]
    slug = LOCATION_SLUGS[location]
    return (
        f"/subscriptions/{sub_id}/resourceGroups/rg-{slug}-{pool_group}"
        f"/providers/Microsoft.Network/virtualNetworks/vn-{slug}-{pool_group}"
        f"/subnets/sn-{slug}-{pool_group}"
    )


def build_gcp_launch_configs(pool_id, pool_cfg):
    """Expand GCP pool config into per-zone launchConfigs."""
    image = resolve_gcp_image(pool_cfg["imageset"])
    zones = pool_cfg["zones"]
    machine_type = pool_cfg["machineType"]

    launch_configs = []
    for zone in zones:
        region = zone.rsplit("-", 1)[0]

        # Build disks with zone-specific paths
        disks = []
        for disk_tpl in pool_cfg.get("disks", []):
            disk = dict(disk_tpl)
            ip = dict(disk.get("initializeParams", {}))

            # Add sourceImage to boot disk
            if disk.get("boot"):
                ip["sourceImage"] = image

            # Expand diskType with zone prefix
            if "diskType" in ip:
                ip["diskType"] = f"zones/{zone}/diskTypes/{ip['diskType']}"

            if ip:
                disk["initializeParams"] = ip
            disks.append(disk)

        lc = {}

        if "advancedMachineFeatures" in pool_cfg:
            lc["advancedMachineFeatures"] = pool_cfg["advancedMachineFeatures"]

        lc["capacityPerInstance"] = pool_cfg.get("capacityPerInstance", 1)
        lc["disks"] = disks

        if "guestAccelerators" in pool_cfg:
            # Expand accelerator types with zone prefix
            gas = []
            for ga in pool_cfg["guestAccelerators"]:
                ga = dict(ga)
                at = ga.get("acceleratorType", "")
                if not at.startswith("zones/"):
                    ga["acceleratorType"] = f"zones/{zone}/acceleratorTypes/{at}"
                gas.append(ga)
            lc["guestAccelerators"] = gas

        lc["machineType"] = f"zones/{zone}/machineTypes/{machine_type}"

        if "minCpuPlatform" in pool_cfg:
            lc["minCpuPlatform"] = pool_cfg["minCpuPlatform"]

        lc["networkInterfaces"] = [
            {"accessConfigs": [{"type": "ONE_TO_ONE_NAT"}]}
        ]
        lc["region"] = region

        if "scheduling" in pool_cfg:
            lc["scheduling"] = pool_cfg["scheduling"]

        if "workerConfig" in pool_cfg:
            lc["workerConfig"] = pool_cfg["workerConfig"]

        # GCP pools have a zone field at the launchConfig level
        lc["zone"] = zone

        launch_configs.append(lc)

    return launch_configs


def build_azure_launch_configs(pool_id, pool_cfg):
    """Expand Azure pool config into per-location launchConfigs."""
    azure_images = resolve_azure_images(pool_cfg["imageset"])
    locations = pool_cfg["locations"]
    provider_id = pool_cfg["providerId"]

    # Determine the subnet group (defaults to pool group, can be overridden)
    subnet_group = pool_cfg.get("subnetGroup", pool_id.split("/")[0])

    launch_configs = []
    for location in locations:
        img_id = azure_images[location]

        lc = {}

        if "billingProfile" in pool_cfg:
            lc["billingProfile"] = pool_cfg["billingProfile"]

        lc["capacityPerInstance"] = pool_cfg.get("capacityPerInstance", 1)

        if "diagnosticsProfile" in pool_cfg:
            lc["diagnosticsProfile"] = pool_cfg["diagnosticsProfile"]

        if "evictionPolicy" in pool_cfg:
            lc["evictionPolicy"] = pool_cfg["evictionPolicy"]

        lc["hardwareProfile"] = {"vmSize": pool_cfg["vmSize"]}
        lc["location"] = location

        if "osProfile" in pool_cfg:
            lc["osProfile"] = pool_cfg["osProfile"]

        if "priority" in pool_cfg:
            lc["priority"] = pool_cfg["priority"]

        # Storage profile
        storage = {"imageReference": {"id": img_id}}
        if "dataDisks" in pool_cfg:
            storage["dataDisks"] = pool_cfg["dataDisks"]
        if "osDisk" in pool_cfg:
            storage["osDisk"] = pool_cfg["osDisk"]
        lc["storageProfile"] = storage

        # SubnetId
        sub_id = AZURE_SUBSCRIPTIONS[provider_id]
        slug = LOCATION_SLUGS[location]
        lc["subnetId"] = (
            f"/subscriptions/{sub_id}/resourceGroups/rg-{slug}-{subnet_group}"
            f"/providers/Microsoft.Network/virtualNetworks/vn-{slug}-{subnet_group}"
            f"/subnets/sn-{slug}-{subnet_group}"
        )

        if "tags" in pool_cfg:
            lc["tags"] = pool_cfg["tags"]

        if "workerConfig" in pool_cfg:
            lc["workerConfig"] = pool_cfg["workerConfig"]

        launch_configs.append(lc)

    return launch_configs


def generate_worker_pools():
    """Generate worker pool JSON from config YAML."""
    pools_cfg = load_yaml("worker-pools.yml")
    result = []

    for pool_id, cfg in pools_cfg.items():
        cloud = cfg["cloud"]

        if cloud == "gcp":
            launch_configs = build_gcp_launch_configs(pool_id, cfg)
        elif cloud == "azure":
            launch_configs = build_azure_launch_configs(pool_id, cfg)
        else:
            raise ValueError(f"Unknown cloud {cloud} for pool {pool_id}")

        pool = {
            "config": {
                "launchConfigs": launch_configs,
                "lifecycle": cfg.get("lifecycle", {}),
                "maxCapacity": cfg.get("maxCapacity", 0),
                "minCapacity": cfg.get("minCapacity", 0),
                "scalingRatio": cfg.get("scalingRatio", 1),
            },
            "description": DESCRIPTION_PREFIX + cfg.get("description", ""),
            "emailOnError": cfg.get("emailOnError", False),
            "owner": cfg.get("owner", ""),
            "providerId": cfg["providerId"],
            "workerPoolId": pool_id,
        }

        result.append(pool)

    return result
