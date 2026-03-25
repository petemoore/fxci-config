# fxci-config Normalization v3 Approach C

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a hybrid config system that generates 1,844 Taskcluster resources from declarative YAML, using community-tc-config's imageset + grants pattern with flat (no-decorator) pool definitions.

**Architecture:** YAML config files define imagesets (image indirection), grants (scope assignments), projects (hooks/clients/managed), and flat worker pools (one entry per pool, no templates/variants/by-keying). Python generation code reads these configs and produces 5 JSON files matching the baseline. A comparison script validates output against baseline/.

**Tech Stack:** Python 3.11+, PyYAML, standard library json/difflib

---

## File Structure

```
config/
  imagesets.yml          # Logical image name -> cloud image IDs (GCP/Azure)
  environments.yml       # Provider config, cloud infrastructure constants
  worker-pools.yml       # 251 flat pool definitions (each fully specified)
  grants.yml             # Scope grants -> generates roles (679)
  projects.yml           # Projects -> generates hooks (679), clients (235)
  managed.yml            # Managed resource patterns (553)
generate/
  __init__.py
  loader.py              # YAML loading utilities
  imagesets.py           # Imageset resolution
  worker_pools.py        # Worker pool JSON generation
  grants.py              # Role generation from grants
  projects.py            # Hook + client generation
  managed.py             # Managed pattern generation
scripts/
  generate.py            # CLI: read config/ -> write output/
  compare.py             # CLI: diff output/ vs baseline/
  extract_imagesets.py   # One-shot: extract imagesets from baseline
  extract_pools.py       # One-shot: extract pool YAML from baseline
  extract_grants.py      # One-shot: extract grants from baseline roles
  extract_projects.py    # One-shot: extract projects from baseline hooks/clients
```

---

## Phase 1: Comparison Infrastructure + Worker Pools

### Task 1: Comparison Script

**Files:**
- Create: `scripts/compare.py`

- [ ] **Step 1: Write compare.py**

Reads `output/*.json` and `baseline/*.json`, does semantic JSON comparison (sorted lists, normalized keys). Reports per-file: matching count, missing, extra, differing entries. Identifies resources by their ID field (workerPoolId, roleId, clientId, hookGroupId+hookId).

- [ ] **Step 2: Test with empty output**

Run: `mkdir -p output && python scripts/compare.py`
Expected: Reports 0/251 pools, 0/679 roles, etc.

- [ ] **Step 3: Commit**

---

### Task 2: Extract Imagesets from Baseline

**Files:**
- Create: `scripts/extract_imagesets.py`
- Create: `config/imagesets.yml`

- [ ] **Step 1: Write extraction script**

Reads `baseline/workerpools.json`, groups pools by their source image (GCP: `sourceImage` field in launchConfig disks; Azure: `imageReference.id`). Outputs `config/imagesets.yml` with logical names and cloud image IDs.

Naming convention for imagesets:
- GCP: derive from image path (e.g., `docker-firefoxci-gcp-l1-2024-06-14` from the sourceImage)
- Azure: derive from image name in the reference

- [ ] **Step 2: Run extraction, review output**

Run: `python scripts/extract_imagesets.py`
Review: `config/imagesets.yml` should have ~15-20 imagesets covering all 79 unique images

- [ ] **Step 3: Commit**

---

### Task 3: Extract Flat Pool Definitions

**Files:**
- Create: `scripts/extract_pools.py`
- Create: `config/worker-pools.yml`

- [ ] **Step 1: Write extraction script**

Reads `baseline/workerpools.json`, produces `config/worker-pools.yml` with each pool as a flat YAML entry. For each pool:
- `workerPoolId` becomes the YAML key
- `providerId`, `description`, `owner`, `emailOnError` are direct fields
- `config.launchConfigs` is preserved but `sourceImage` / `imageReference.id` replaced with `imageset` reference
- `config.lifecycle`, `config.maxCapacity`, `config.minCapacity` are direct fields

- [ ] **Step 2: Run extraction, review output**

Run: `python scripts/extract_pools.py`
Review: `config/worker-pools.yml` should have 251 pool entries

- [ ] **Step 3: Commit**

---

### Task 4: Worker Pool Generation Code

**Files:**
- Create: `generate/__init__.py`
- Create: `generate/loader.py`
- Create: `generate/imagesets.py`
- Create: `generate/worker_pools.py`
- Create: `scripts/generate.py`

- [ ] **Step 1: Write loader.py**

Simple YAML file loading with path resolution relative to config/.

- [ ] **Step 2: Write imagesets.py**

Loads `config/imagesets.yml`, provides `resolve_image(imageset_name, provider)` -> image ID string.

- [ ] **Step 3: Write worker_pools.py**

Loads `config/worker-pools.yml`, resolves imageset references in launchConfigs, produces list of worker pool dicts matching baseline format. Key: the `description` field gets the standard "DO NOT EDIT" prefix prepended.

- [ ] **Step 4: Write generate.py (worker pools only)**

CLI entry point. Loads configs, calls worker_pools generator, writes `output/workerpools.json`.

- [ ] **Step 5: Run generation + comparison**

```bash
python scripts/generate.py
python scripts/compare.py
```

Expected: 251/251 worker pools matching (or close - iterate on differences).

- [ ] **Step 6: Fix discrepancies and iterate**

Compare output carefully, fix generation code until `compare.py` reports 251/251 match.

- [ ] **Step 7: Commit**

---

## Phase 2: Roles from Grants

### Task 5: Extract Grants from Baseline Roles

**Files:**
- Create: `scripts/extract_grants.py`
- Create: `config/grants.yml`

- [ ] **Step 1: Write extraction script**

Reads `baseline/roles.json`, produces `config/grants.yml`. Since approach C uses flat definitions (no decorators), each role maps directly to a grant entry:

```yaml
- roleId: "hook-id:project-comm/in-tree-action-3-*"
  scopes:
    - "assume:repo:hg.mozilla.org/releases/comm-esr115:action:*"
    - ...
```

This is essentially the roles list in YAML form but structured as grants.

- [ ] **Step 2: Run extraction, review output**

- [ ] **Step 3: Commit**

---

### Task 6: Role Generation Code

**Files:**
- Create: `generate/grants.py`
- Modify: `scripts/generate.py`

- [ ] **Step 1: Write grants.py**

Loads `config/grants.yml`, produces list of role dicts matching baseline format. Adds "DO NOT EDIT" description prefix.

- [ ] **Step 2: Update generate.py to include roles**

- [ ] **Step 3: Run generation + comparison**

Expected: 679/679 roles matching.

- [ ] **Step 4: Fix discrepancies and iterate**

- [ ] **Step 5: Commit**

---

## Phase 3: Hooks + Clients from Projects

### Task 7: Extract Projects (Hooks + Clients)

**Files:**
- Create: `scripts/extract_projects.py`
- Create: `config/projects.yml`

- [ ] **Step 1: Write extraction script**

Reads `baseline/hooks.json` and `baseline/clients.json`, groups by project, produces `config/projects.yml`. Each project has its hooks and clients listed.

- [ ] **Step 2: Run extraction, review output**

- [ ] **Step 3: Commit**

---

### Task 8: Hook + Client Generation Code

**Files:**
- Create: `generate/projects.py`
- Modify: `scripts/generate.py`

- [ ] **Step 1: Write projects.py**

Loads `config/projects.yml`, produces hook and client dicts matching baseline format.

- [ ] **Step 2: Update generate.py to include hooks + clients**

- [ ] **Step 3: Run generation + comparison**

Expected: 679/679 hooks, 235/235 clients matching.

- [ ] **Step 4: Fix discrepancies and iterate**

- [ ] **Step 5: Commit**

---

## Phase 4: Managed Patterns

### Task 9: Extract + Generate Managed Patterns

**Files:**
- Create: `config/managed.yml`
- Create: `generate/managed.py`
- Modify: `scripts/generate.py`

- [ ] **Step 1: Write managed.yml**

Direct extraction from `baseline/managed.json` - these are regex patterns.

- [ ] **Step 2: Write managed.py generation**

- [ ] **Step 3: Update generate.py, run comparison**

Expected: 553/553 managed patterns matching.

- [ ] **Step 4: Commit**

---

## Phase 5: Final Validation

### Task 10: Full Comparison Pass

- [ ] **Step 1: Run full generation**

```bash
python scripts/generate.py
python scripts/compare.py
```

Expected: All 5 files match baseline exactly.

- [ ] **Step 2: Clean up extraction scripts** (move to scripts/oneshot/ or delete)

- [ ] **Step 3: Final commit**
