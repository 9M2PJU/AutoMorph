"""
GitHub Releases Update Checker for AutoMorph Web Portal.

Queries GitHub Releases API to detect new published releases and pre-releases,
separated by channel track ('dev' vs 'main'). Supports ETag caching and force cooldown.
"""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any

import requests

logger = logging.getLogger("automorph.update_checker")

# Root directory of the repository/container
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
VERSION_FILE = ROOT_DIR / "web" / "version.json"

DEFAULT_REPO = "holjab/automorph"
CACHE_TTL_SECONDS = 1800.0  # 30 minutes for automatic background checks
FORCE_COOLDOWN_SECONDS = 60.0  # 60s cooldown for manual 'Check Again' button

# Global in-memory cache
_cache: dict[str, Any] = {
    "data": None,
    "etag": None,
    "last_check_time": 0.0,
}


def parse_semver(ver_str: str) -> tuple[int, int, int, int, int]:
    """
    Parses semantic version strings like 'v1.2.3', '0.01', '1.0.0-dev.1', 'v0.2.0-beta.2'.
    Returns a sortable tuple: (major, minor, patch, is_stable, prerelease_build_num).
    """
    if not ver_str:
        return (0, 0, 0, 0, 0)

    clean = str(ver_str).strip().lstrip("v").strip()
    match = re.match(
        r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([a-zA-Z0-9.]+))?",
        clean,
    )
    if not match:
        return (0, 0, 0, 0, 0)

    major = int(match.group(1) or 0)
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    prerelease_str = match.group(4) or ""

    # In semver, full release > prerelease of same numbers (e.g. 1.0.0 > 1.0.0-dev.1)
    is_stable = 1 if not prerelease_str else 0

    # Extract build number from prerelease (e.g. dev.1 -> 1)
    pre_num = 0
    if prerelease_str:
        num_match = re.search(r"(\d+)", prerelease_str)
        if num_match:
            pre_num = int(num_match.group(1))

    return (major, minor, patch, is_stable, pre_num)


def get_local_version_metadata() -> dict[str, Any]:
    """
    Reads local web/version.json.
    Extracts version, tag, branch, commit, and build date.
    """
    if not VERSION_FILE.is_file():
        return {
            "valid": False,
            "version": os.getenv("APP_VERSION", "0.01"),
            "tag": "v0.01",
            "branch": os.getenv("UPDATE_CHANNEL", "dev"),
            "commit": "",
            "short_commit": "",
        }

    try:
        with VERSION_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        branch = data.get("branch") or os.getenv("UPDATE_CHANNEL", "dev")
        version = data.get("version") or "0.01"
        tag = data.get("tag") or f"v{version}"
        commit = data.get("commit") or ""

        return {
            "valid": True,
            "branch": str(branch).strip(),
            "version": str(version).strip(),
            "tag": str(tag).strip(),
            "commit": str(commit).strip(),
            "short_commit": str(commit)[:7] if commit else "",
            "built_at": data.get("built_at"),
        }
    except Exception as e:
        logger.warning(f"Failed to read local version.json: {e}")
        return {
            "valid": False,
            "version": "0.01",
            "tag": "v0.01",
            "branch": os.getenv("UPDATE_CHANNEL", "dev"),
            "commit": "",
            "short_commit": "",
        }


def check_for_updates(force: bool = False) -> dict[str, Any]:
    """
    Checks GitHub Releases for updates.
    - 'main' channel: tracks latest stable release (prerelease == False).
    - 'dev' channel: tracks newest release or pre-release (prerelease == True).
    """
    now = time.time()
    local_info = get_local_version_metadata()
    branch = local_info.get("branch") or "dev"
    local_version = local_info.get("version") or "0.01"
    local_tag = local_info.get("tag") or f"v{local_version}"
    local_short_commit = local_info.get("short_commit") or ""

    # Check force cooldown (60 seconds)
    time_since_last_check = now - _cache["last_check_time"]
    if force and _cache["data"] is not None and time_since_last_check < FORCE_COOLDOWN_SECONDS:
        cached_result = dict(_cache["data"])
        remaining = int(FORCE_COOLDOWN_SECONDS - time_since_last_check)
        cached_result["cooldown"] = True
        cached_result["cooldown_remaining"] = remaining
        cached_result["cached"] = True
        return cached_result

    # Check regular cache TTL (30 minutes)
    if not force and _cache["data"] is not None and time_since_last_check < CACHE_TTL_SECONDS:
        cached_result = dict(_cache["data"])
        cached_result["cached"] = True
        cached_result["cooldown"] = False
        cached_result["cooldown_remaining"] = 0
        return cached_result

    repo = os.getenv("GITHUB_REPOSITORY", DEFAULT_REPO).strip()
    url = f"https://api.github.com/repos/{repo}/releases"
    params = {"per_page": 20}

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "AutoMorph-UpdateChecker",
    }

    # Optional GitHub Token from environment (required if private repo)
    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token.strip()}"

    # ETag support to preserve rate limits
    if _cache["etag"]:
        headers["If-None-Match"] = _cache["etag"]

    try:
        _cache["last_check_time"] = now
        res = requests.get(url, params=params, headers=headers, timeout=6.0)

        # 304 Not Modified: reuse cached result, 0 quota cost
        if res.status_code == 304 and _cache["data"] is not None:
            cached_result = dict(_cache["data"])
            cached_result["cached"] = True
            cached_result["cooldown"] = False
            cached_result["cooldown_remaining"] = 0
            cached_result["checked_at"] = datetime.now(timezone.utc).isoformat()
            return cached_result

        # Handle rate limits
        if res.status_code == 403:
            logger.warning("GitHub API rate limit exceeded when checking for releases.")
            err_res = {
                "update_available": None,
                "status": "error",
                "branch": branch,
                "current_version": local_version,
                "current_tag": local_tag,
                "current_commit": local_short_commit,
                "error": "GitHub API rate limit exceeded. Please try again later.",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "cached": False,
                "cooldown": False,
                "cooldown_remaining": 0,
            }
            _cache["data"] = err_res
            return err_res

        # Handle 404 (private repo or repo not found)
        if res.status_code == 404:
            err_msg = (
                f"Repository not found or access denied ({repo}). "
                "If private, ensure a valid GITHUB_TOKEN is configured in .env."
            )
            err_res = {
                "update_available": None,
                "status": "error",
                "branch": branch,
                "current_version": local_version,
                "current_tag": local_tag,
                "current_commit": local_short_commit,
                "error": err_msg,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "cached": False,
                "cooldown": False,
                "cooldown_remaining": 0,
            }
            _cache["data"] = err_res
            return err_res

        res.raise_for_status()

        # Update cached ETag
        etag = res.headers.get("ETag")
        if etag:
            _cache["etag"] = etag

        releases = res.json()
        if not isinstance(releases, list) or not releases:
            result = {
                "update_available": False,
                "status": "up_to_date",
                "branch": branch,
                "current_version": local_version,
                "current_tag": local_tag,
                "current_commit": local_short_commit,
                "latest_version": local_version,
                "latest_tag": local_tag,
                "release_name": "No Releases Published Yet",
                "release_notes": "No official releases have been published to GitHub yet.",
                "release_url": None,
                "published_at": None,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "cached": False,
                "cooldown": False,
                "cooldown_remaining": 0,
                "error": None,
            }
            _cache["data"] = result
            return result

        # Select target release based on track channel:
        # - main: only stable releases (prerelease == False, draft == False)
        # - dev: newest published release (whether prerelease or stable)
        target_release = None
        is_dev_track = (branch.lower() == "dev")

        for r in releases:
            if r.get("draft"):
                continue
            if is_dev_track:
                # First non-draft release (can be prerelease or stable)
                target_release = r
                break
            else:
                # Main track: must NOT be prerelease
                if not r.get("prerelease"):
                    target_release = r
                    break

        if not target_release:
            # No matching releases for this channel
            result = {
                "update_available": False,
                "status": "up_to_date",
                "branch": branch,
                "current_version": local_version,
                "current_tag": local_tag,
                "current_commit": local_short_commit,
                "latest_version": local_version,
                "latest_tag": local_tag,
                "release_name": f"No {branch} releases found",
                "release_notes": f"No published releases found for the '{branch}' track.",
                "release_url": None,
                "published_at": None,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "cached": False,
                "cooldown": False,
                "cooldown_remaining": 0,
                "error": None,
            }
            _cache["data"] = result
            return result

        rel_tag = target_release.get("tag_name", "").strip()
        rel_name = target_release.get("name") or rel_tag
        rel_body = target_release.get("body") or "No release notes provided."
        rel_url = target_release.get("html_url")
        rel_prerelease = bool(target_release.get("prerelease"))
        published_at = target_release.get("published_at") or target_release.get("created_at")

        # Compare version strings
        local_parsed = parse_semver(local_version)
        remote_parsed = parse_semver(rel_tag)

        update_available = False
        if rel_tag and local_tag and rel_tag.lower() == local_tag.lower():
            update_available = False
        elif remote_parsed > local_parsed:
            update_available = True
        elif remote_parsed == local_parsed and remote_parsed != (0, 0, 0, 0, 0):
            # Same numbers, check tag string difference
            update_available = (rel_tag != local_tag)
        elif rel_tag and (local_version in ("0.01", "unknown")):
            # Initial placeholder version: any real release is an update
            update_available = True

        clean_remote_ver = rel_tag.lstrip("v") if rel_tag.startswith("v") else rel_tag

        result = {
            "update_available": update_available,
            "status": "update_available" if update_available else "up_to_date",
            "branch": branch,
            "is_prerelease": rel_prerelease,
            "current_version": local_version,
            "current_tag": local_tag,
            "current_commit": local_short_commit,
            "latest_version": clean_remote_ver,
            "latest_tag": rel_tag,
            "release_name": rel_name,
            "release_notes": rel_body,
            "release_url": rel_url,
            "published_at": published_at,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "cached": False,
            "cooldown": False,
            "cooldown_remaining": 0,
            "error": None,
        }

        _cache["data"] = result
        return result

    except requests.RequestException as e:
        logger.warning(f"Network error querying GitHub Releases: {e}")
        err_res = {
            "update_available": None,
            "status": "error",
            "branch": branch,
            "current_version": local_version,
            "current_tag": local_tag,
            "current_commit": local_short_commit,
            "error": f"Could not reach GitHub Releases: {e}",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "cached": False,
            "cooldown": False,
            "cooldown_remaining": 0,
        }
        _cache["data"] = err_res
        return err_res
    except Exception as e:
        logger.exception("Unexpected error during release check")
        return {
            "update_available": None,
            "status": "error",
            "branch": branch,
            "current_version": local_version,
            "current_tag": local_tag,
            "current_commit": local_short_commit,
            "error": f"Unexpected error during release check: {e}",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "cached": False,
            "cooldown": False,
            "cooldown_remaining": 0,
        }
