"""Fetch .taskcluster.yml from project repositories.

Downloads and hashes .taskcluster.yml from each project's repo,
caching results in output/tcyml_cache/.
"""

import hashlib
import json
import os
import re
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import yaml

from .loader import load_yaml

CACHE_DIR = Path(__file__).resolve().parent.parent / "output" / "tcyml_cache"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")


def _hash_tcyml(content_bytes):
    """Hash .taskcluster.yml content (matches taskgraph's hashing)."""
    return hashlib.sha256(content_bytes).hexdigest()[:10]


def _fetch_hg(repo_url, branch="default"):
    """Fetch .taskcluster.yml from an hg.mozilla.org repo."""
    url = f"{repo_url}/raw-file/{branch}/.taskcluster.yml"
    req = Request(url, headers={"User-Agent": "fxci-config/v3c"})
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read()
    except HTTPError as e:
        if e.code == 404:
            return None
        raise


def _fetch_github(repo_url, branch="main"):
    """Fetch .taskcluster.yml from a GitHub repo."""
    # https://github.com/org/repo -> /repos/org/repo/contents/.taskcluster.yml
    repo_path = repo_url.replace("https://github.com/", "")
    if repo_path.endswith("/"):
        repo_path = repo_path[:-1]
    url = f"https://api.github.com/repos/{repo_path}/contents/.taskcluster.yml?ref={branch}"
    headers = {
        "User-Agent": "fxci-config/v3c",
        "Accept": "application/vnd.github.raw+json",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read()
    except HTTPError as e:
        if e.code == 404:
            return None
        raise


def _get_github_branches(repo_url):
    """Get list of branch names from a GitHub repo."""
    repo_path = repo_url.replace("https://github.com/", "")
    if repo_path.endswith("/"):
        repo_path = repo_path[:-1]
    # For globbed repos (org/*), we can't list branches
    if "*" in repo_path:
        return []
    url = f"https://api.github.com/repos/{repo_path}/branches?per_page=100"
    headers = {"User-Agent": "fxci-config/v3c"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return [b["name"] for b in data]
    except HTTPError:
        return []


def _glob_match(patterns, value):
    """Check if value matches any of the glob patterns."""
    for pat in patterns:
        if pat == value:
            return True
        if pat == "*":
            return True
        # Simple glob: convert to regex
        regex = "^" + re.escape(pat).replace(r"\*", ".*") + "$"
        if re.match(regex, value):
            return True
    return False


def _should_hash(project):
    """Determine if a project needs .taskcluster.yml hashing."""
    features = project.get("features", {})
    if features.get("gecko-actions"):
        if not features.get("hg-push") and not features.get("taskgraph-cron"):
            return False
        if project.get("is_try"):
            return False
        return True
    elif features.get("taskgraph-actions"):
        repo = project.get("repo", "")
        if "*" in repo:
            return False
        if features.get("github-private-repo"):
            return False
        return True
    return False


def _get_default_branch(project):
    """Get default branch name for a project."""
    repo_type = project.get("repo_type", "hg")
    if repo_type == "hg":
        return "default"
    return "main"


def _get_level(project, branch_name):
    """Get the SCM level for a project at a given branch."""
    branches = project.get("branches", [])
    for b in branches:
        if isinstance(b, dict):
            if b.get("name") == branch_name or _glob_match([b.get("name", "")], branch_name):
                if "level" in b:
                    return b["level"]
    # Default level from access
    access = project.get("access", "scm_level_1")
    m = re.match(r"scm_level_(\d+)", access)
    return int(m.group(1)) if m else 1


def fetch_all_tcymls(use_cache=True, cache_only=False):
    """Fetch and hash .taskcluster.yml from all projects.

    Returns: {alias: {branch: {"parsed": dict, "hash": str, "level": int}}}
    """
    projects = load_yaml("projects.yml")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / "tcyml_cache.json"

    # Load cache
    cache = {}
    if use_cache and cache_file.exists():
        cache = json.loads(cache_file.read_text())

    result = {}

    for alias, proj in projects.items():
        if not _should_hash(proj):
            continue

        repo = proj.get("repo", "")
        repo_type = proj.get("repo_type", "hg")
        default_branch = _get_default_branch(proj)

        # Get branches to fetch
        if repo_type == "hg":
            branches_to_check = [default_branch]
        else:
            # Get configured branches (excluding bare "*")
            configured = []
            for b in proj.get("branches", []):
                name = b.get("name", b) if isinstance(b, dict) else b
                if name != "*":
                    configured.append(name)
            configured.append(default_branch)

            # Get actual branches from GitHub (or from cache keys)
            if cache_only:
                # Derive branches from cache keys
                remote_branches = [
                    k.split("@")[1] for k in cache
                    if k.startswith(f"{repo}@")
                ]
            else:
                remote_branches = _get_github_branches(repo)
            branches_to_check = [
                b for b in remote_branches
                if _glob_match(configured, b)
            ]
            if not branches_to_check:
                branches_to_check = [default_branch]

        result[alias] = {}

        for branch in branches_to_check:
            cache_key = f"{repo}@{branch}"

            if cache_key in cache:
                entry = cache[cache_key]
                if entry is None:
                    continue
                result[alias][branch] = {
                    "parsed": entry["parsed"],
                    "hash": entry["hash"],
                    "level": _get_level(proj, branch),
                    "alias": alias,
                }
                continue

            if cache_only:
                continue

            # Fetch
            print(f"  Fetching {alias} @ {branch}...")
            try:
                if repo_type == "hg":
                    content = _fetch_hg(repo, branch)
                else:
                    content = _fetch_github(repo, branch)
            except Exception as e:
                print(f"    Error: {e}")
                cache[cache_key] = None
                continue

            if not content:
                cache[cache_key] = None
                continue

            try:
                parsed = yaml.safe_load(content)
            except Exception:
                cache[cache_key] = None
                continue

            if not isinstance(parsed.get("tasks"), list):
                cache[cache_key] = None
                continue

            h = _hash_tcyml(content)
            entry = {"parsed": parsed, "hash": h}
            cache[cache_key] = entry
            result[alias][branch] = {
                "parsed": parsed,
                "hash": h,
                "level": _get_level(proj, branch),
                "alias": alias,
            }

    # Save cache
    cache_file.write_text(json.dumps(cache, indent=2, sort_keys=True))
    return result
