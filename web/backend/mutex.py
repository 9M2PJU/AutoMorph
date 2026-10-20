"""
Cross-container heartbeat-based execution mutex for AutoMorph.
Prevents concurrent pipeline builds between the web interface and background scheduler.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import time
from typing import Any

logger = logging.getLogger("automorph.mutex")

# Project root resolution
PROJECT_ROOT = Path(os.getenv("AUTOMORPH_ROOT", Path(__file__).resolve().parent.parent.parent))
APPS_DIR = PROJECT_ROOT / "apps"
LOCK_FILE = APPS_DIR / ".automorph.lock"
HEARTBEAT_TIMEOUT_SECONDS = 300  # 5 minutes threshold for stale locks

# In-memory asyncio lock for the web process
_asyncio_lock = asyncio.Lock()


def get_lock_path() -> Path:
    APPS_DIR.mkdir(parents=True, exist_ok=True)
    return LOCK_FILE


def get_active_lock() -> dict[str, Any] | None:
    """
    Inspects the lock file. If it exists and the heartbeat is fresh (<= 300s old),
    returns the lock metadata dict. If stale (> 300s), deletes the stale file and returns None.
    """
    lock_path = get_lock_path()
    if not lock_path.is_file():
        return None

    try:
        content = lock_path.read_text(encoding="utf-8").strip()
        if not content:
            lock_path.unlink(missing_ok=True)
            return None
        data = json.loads(content)
    except Exception as e:
        logger.warning(f"Corrupted lock file encountered, clearing: {e}")
        lock_path.unlink(missing_ok=True)
        return None

    updated_at = data.get("updated_at") or data.get("started_at", 0)
    age = time.time() - updated_at

    if age > HEARTBEAT_TIMEOUT_SECONDS:
        logger.warning(
            f"Stale lock detected (no heartbeat for {int(age)}s > {HEARTBEAT_TIMEOUT_SECONDS}s). "
            f"Auto-reclaiming lock for run {data.get('run_id')}."
        )
        lock_path.unlink(missing_ok=True)
        return None

    return data


def acquire_lock(
    source: str = "manual",
    package: str | None = None,
    container: str = "automorph_web",
    run_id: str | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    """
    Attempts to acquire the heartbeat file lock.
    Returns (True, new_lock_data) on success, or (False, active_lock_data) on failure.
    """
    active = get_active_lock()
    if active is not None:
        return False, active

    now = time.time()
    lock_data = {
        "run_id": run_id or f"run-{int(now)}",
        "source": source,
        "package": package,
        "container": container,
        "started_at": now,
        "updated_at": now,
    }

    try:
        lock_path = get_lock_path()
        lock_path.write_text(json.dumps(lock_data, indent=2), encoding="utf-8")
        logger.info(f"Acquired execution mutex for run_id: {lock_data['run_id']} ({source}, pkg: {package})")
        return True, lock_data
    except Exception as e:
        logger.error(f"Failed to write lock file: {e}")
        return False, {"error": str(e)}


def update_heartbeat() -> bool:
    """
    Updates the updated_at timestamp in the lock file to maintain freshness.
    """
    lock_path = get_lock_path()
    if not lock_path.is_file():
        return False

    try:
        content = lock_path.read_text(encoding="utf-8")
        data = json.loads(content)
        data["updated_at"] = time.time()
        lock_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        logger.warning(f"Failed to update lock heartbeat: {e}")
        return False


def release_lock() -> bool:
    """
    Removes the lock file safely.
    """
    lock_path = get_lock_path()
    try:
        if lock_path.is_file():
            lock_path.unlink(missing_ok=True)
            logger.info("Released execution mutex.")
        return True
    except Exception as e:
        logger.error(f"Error releasing lock file: {e}")
        return False
