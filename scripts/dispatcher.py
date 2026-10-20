"""
Email dispatcher module for Morphe Patcher.

Constructs Tailscale Funnel download links for patched APKs,
inspects result.json and options files for nuanced patch audits
(Applied, Explicitly Failed, Superseded by Alias, Not Applied),
reports severe pipeline failures and fallback progressions, and
sends clean, modern dual-MIME (HTML + Plain Text) notification emails
styled in the Morphe "Obsidian Cyber Synthetics" design system.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
import hashlib
import html
import json
import os
import re
from pathlib import Path
import smtplib
import time
from typing import Any
from urllib.parse import quote, urljoin, urlparse

from dotenv import load_dotenv
import yaml
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration & Helpers
# ---------------------------------------------------------------------------

def load_config(project_root: Path | None = None) -> dict:
    """
    Loads config.yaml from project root and initializes environment variables.
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent

    config_path = project_root / "tools" / "automorph-data" / "config.yaml"
    if not config_path.is_file():
        raise FileNotFoundError(f"Missing config.yaml at {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Load environment variables if .env specified
    env_rel = config.get("env_location", ".env")
    env_path = (project_root / env_rel).resolve()
    if env_path.is_file():
        load_dotenv(dotenv_path=env_path)

    # Resolve credentials from environment (.env) or config
    email_conf = config.setdefault("email", {})
    email_conf["username"] = (
        email_conf.get("username")
        or (os.getenv(email_conf.get("username_env")) if email_conf.get("username_env") else None)
        or os.getenv("SMTP_USERNAME")
        or os.getenv("SMTP_USER")
        or email_conf.get("sender_email", "")
    )
    email_conf["password"] = (
        email_conf.get("password")
        or (os.getenv(email_conf.get("password_env")) if email_conf.get("password_env") else None)
        or os.getenv("SMTP_PASSWORD")
        or os.getenv("SMTP_PASS")
        or ""
    )

    config["project_root"] = project_root
    return config


def clean_repo_name(repo_url_or_name: str) -> str:
    """
    normalises a repository URL or name to 'owner/repo' format for clean badge display.
    e.g. 'https://github.com/MorpheApp/morphe-patches.git' -> 'MorpheApp/morphe-patches'
    """
    if not repo_url_or_name:
        return ""
    cleaned = str(repo_url_or_name).strip()
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    if ".com/" in cleaned:
        cleaned = cleaned.split(".com/")[1]
    cleaned = cleaned.strip("/")
    return cleaned


def format_strategy_name(strategy: int | str | None, short: bool = False) -> str:
    """
    Translates run/strategy integers into clear, human-readable strategy names.
    - 1 -> 'Strategy 1 (All Patches)' or 'Strategy 1'
    - 2 -> 'Strategy 2 (Version-Compatible)' or 'Strategy 2'
    """
    if strategy in (1, "1", "force", "all"):
        return "Strategy 1" if short else "Strategy 1 (All Patches)"
    elif strategy in (2, "2", "fallback", "compat", "compatible"):
        return "Strategy 2" if short else "Strategy 2 (Version-Compatible)"
    if not strategy:
        return "Strategy 1" if short else "Strategy 1 (All Patches)"
    return f"Strategy {strategy}"


def normalize_base_url(url: str | None) -> str:
    """Ensures URL starts with http:// or https:// and has no trailing slash. Safe against None/empty."""
    if not url:
        return ""
    clean = str(url).strip()
    if not clean:
        return ""
    if not clean.startswith("http://") and not clean.startswith("https://"):
        clean = "https://" + clean
    return clean.rstrip("/")


def resolve_tunnel_endpoints(config: dict | None = None) -> list[dict]:
    """
    Detects and normalizes all active tunnel base URLs.
    Checks COMPOSE_PROFILES and specific environment variables:
      - CLOUDFLARE_TUNNEL_URL
      - PANGOLIN_URL
      - TAILSCALE_FUNNEL_URL (or TAILSCALE_URL)
    Falls back to legacy config.tailscale.base_url or local origin (http://localhost:8080).
    Never crashes if any option is empty or missing.
    """
    config = config or {}
    endpoints = []
    profiles_env = os.getenv("COMPOSE_PROFILES", "").strip()
    active_profiles = [p.strip().lower() for p in profiles_env.split(",") if p.strip()]

    cf_url_raw = os.getenv("CLOUDFLARE_TUNNEL_URL", "").strip()
    pangolin_url_raw = os.getenv("PANGOLIN_URL", "").strip()
    
    ts_conf = config.get("tailscale")
    ts_config_base = str(ts_conf.get("base_url") or "") if isinstance(ts_conf, dict) else ""
    ts_url_raw = (
        os.getenv("TAILSCALE_FUNNEL_URL", "").strip()
        or os.getenv("TAILSCALE_URL", "").strip()
        or ts_config_base.strip()
    )

    if active_profiles:
        if "cloudflare" in active_profiles and cf_url_raw:
            endpoints.append({
                "id": "cloudflare",
                "label": "Cloudflare",
                "badge": "CF",
                "icon": "☁️",
                "color": "#0284c7",
                "base_url": normalize_base_url(cf_url_raw),
            })
        if "pangolin" in active_profiles and pangolin_url_raw:
            endpoints.append({
                "id": "pangolin",
                "label": "Pangolin",
                "badge": "Pangolin",
                "icon": "🌐",
                "color": "#7c3aed",
                "base_url": normalize_base_url(pangolin_url_raw),
            })
        if "tailscale" in active_profiles and ts_url_raw:
            endpoints.append({
                "id": "tailscale",
                "label": "Tailscale",
                "badge": "TS",
                "icon": "🔒",
                "color": "#0284c7",
                "base_url": normalize_base_url(ts_url_raw),
            })
    else:
        # If COMPOSE_PROFILES not explicitly set, activate any configured tunnel URL
        if cf_url_raw:
            endpoints.append({
                "id": "cloudflare",
                "label": "Cloudflare",
                "badge": "CF",
                "icon": "☁️",
                "color": "#0284c7",
                "base_url": normalize_base_url(cf_url_raw),
            })
        if pangolin_url_raw:
            endpoints.append({
                "id": "pangolin",
                "label": "Pangolin",
                "badge": "Pangolin",
                "icon": "🌐",
                "color": "#7c3aed",
                "base_url": normalize_base_url(pangolin_url_raw),
            })
        if ts_url_raw:
            endpoints.append({
                "id": "tailscale",
                "label": "Tailscale",
                "badge": "TS",
                "icon": "🔒",
                "color": "#0284c7",
                "base_url": normalize_base_url(ts_url_raw),
            })

    # Fallback to local origin if no endpoints are active
    if not endpoints:
        endpoints.append({
            "id": "local",
            "label": "Local",
            "badge": "Local",
            "icon": "⚡",
            "color": "#0284c7",
            "base_url": "http://localhost:8080",
        })

    return endpoints


def build_funnel_url(apk_path: Path | None, serve_root: Path | None, base_url: str | None) -> str | None:
    """
    Constructs a download URL for an APK or web report.
    URL encodes individual path segments to handle spaces or special characters safely.
    Returns None if apk_path is not within serve_root or arguments are invalid.
    """
    if not apk_path or not serve_root or not base_url:
        return None
    try:
        rel_path = apk_path.resolve().relative_to(serve_root.resolve())
    except Exception:
        return None

    encoded_parts = [quote(part, safe="") for part in rel_path.parts]
    relative_url = "/".join(encoded_parts)

    norm_base = normalize_base_url(base_url)
    return f"{norm_base}/{relative_url}" if norm_base else None


def get_enabled_patches_from_options(
    options_dir: Path | None,
    package_name: str,
    options_file: Path | None = None,
) -> list[str]:
    """
    Reads an options JSON file for a package to extract patches marked enabled=True.
    Defensively parses either:
      - A single dict: {"patches": [{"name": "...", "enabled": true}, ...]}
      - A list of bundles: [{"patches": [{"name": "...", "enabled": true}, ...]}, ...]
    """
    target_file = None

    if options_file and options_file.is_file():
        target_file = options_file
    elif options_dir:
        pkg_dir = options_dir / package_name
        if pkg_dir.is_dir():
            candidates = sorted(
                pkg_dir.glob("*.json"),
                key=lambda p: (0 if "merge" in p.name else 1, p.stat().st_mtime),
                reverse=True,
            )
            if candidates:
                target_file = candidates[0]

    if not target_file or not target_file.is_file():
        return []

    try:
        data = json.loads(target_file.read_text(encoding="utf-8"))
    except Exception:
        return []

    enabled_names: list[str] = []

    def extract_from_patches(p_data: dict | list | None) -> None:
        if isinstance(p_data, dict):
            for patch_name, p_info in p_data.items():
                if isinstance(p_info, dict) and p_info.get("enabled", False) is True:
                    if isinstance(patch_name, str) and patch_name.strip():
                        enabled_names.append(patch_name.strip())
        elif isinstance(p_data, list):
            for p in p_data:
                if isinstance(p, dict) and p.get("enabled", False) is True:
                    name = p.get("name")
                    if isinstance(name, str) and name.strip():
                        enabled_names.append(name.strip())

    if isinstance(data, dict):
        extract_from_patches(data.get("patches"))
    elif isinstance(data, list):
        for block in data:
            if isinstance(block, dict):
                extract_from_patches(block.get("patches"))

    # Return deduplicated while preserving order
    return list(dict.fromkeys(enabled_names))


def inspect_patch_result(
    apk_path: Path,
    options_dir: Path | None = None,
    package_name: str | None = None,
    patch_aliases: dict[str, str] | None = None,
    unapplied_reasons: dict[str, str] | None = None,
    options_file: Path | None = None,
) -> dict:
    """
    Inspects result.json and cross-references with options files and alias mappings
    to provide a factual, non-speculative patch audit:
    - applied_patches: successfully applied patches (from result.json)
    - failed_patches: explicitly failed patches (from result.json)
    - superseded_patches: enabled in options, omitted because an alias partner was applied
    - unapplied_patches: enabled in options, neither applied, failed, nor superseded
    - unsupported_patches: legacy field for backward compatibility; NEVER used for display.
    """
    fallback = {
        "available": False,
        "summary": "Patch details unavailable",
        "applied_patches": [],
        "failed_patches": [],
        "superseded_patches": [],
        "unapplied_patches": [],
        "unsupported_patches": [],
        "enabled_in_options": [],
        "steps": [],
        "raw_json": None,
        "result_file": None,
    }

    result_file = apk_path.parent / "result.json"
    if not result_file.is_file():
        return fallback

    try:
        content = result_file.read_text(encoding="utf-8")
        data = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        logger.warning(f"Note: Could not parse {result_file}: {e}")
        return fallback

    if not isinstance(data, dict):
        return fallback

    # 1. Extract applied patches defensively from result.json
    applied_patches: list[str] = []
    raw_applied = data.get("appliedPatches")
    if isinstance(raw_applied, list):
        for item in raw_applied:
            if isinstance(item, dict):
                name = item.get("name") or item.get("patch") or item.get("patchName") or item.get("title")
                if isinstance(name, dict):
                    name = name.get("name") or name.get("title")
                if isinstance(name, str) and name.strip():
                    applied_patches.append(name.strip())
            elif isinstance(item, str) and item.strip():
                applied_patches.append(item.strip())

    # 2. Extract explicitly failed patches from result.json
    failed_patches: list[dict[str, str]] = []
    raw_failed = data.get("failedPatches")
    if isinstance(raw_failed, list):
        for item in raw_failed:
            if isinstance(item, dict):
                name = item.get("name") or item.get("patch") or item.get("patchName") or item.get("patch_name") or item.get("title") or item.get("id")
                if isinstance(name, dict):
                    name = name.get("name") or name.get("title")
                reason = item.get("reason") or item.get("error") or item.get("message") or item.get("exception") or "Patch failed during execution"
                name_str = str(name).strip() if name else ""
                reason_str = str(reason).strip()
                if not name_str or name_str.lower() in ("patch", "unknown patch", "unknown", "failed patch"):
                    fp_match = re.search(r"([a-zA-Z0-9_]+)Fingerprint", reason_str)
                    if fp_match:
                        name_str = re.sub(r"([a-z])([A-Z])", r"\1 \2", fp_match.group(1))
                    else:
                        patch_match = re.search(r"patches\.[a-zA-Z0-9_.]+\.([a-zA-Z0-9_]+)(?:Patch)?", reason_str)
                        if patch_match:
                            name_str = re.sub(r"([a-z])([A-Z])", r"\1 \2", patch_match.group(1).removesuffix("Patch"))
                        else:
                            name_str = "Failed Patch"
                failed_patches.append({"name": name_str, "reason": reason_str})
            elif isinstance(item, str) and item.strip():
                failed_patches.append({"name": item.strip(), "reason": "Patch failed during execution"})

    # 3. Extract patching steps defensively
    steps = []
    raw_steps = data.get("patchingSteps")
    if isinstance(raw_steps, list):
        for item in raw_steps:
            if isinstance(item, dict):
                step_name = item.get("step")
                success = item.get("success")
                if isinstance(step_name, str):
                    steps.append({"step": step_name, "success": bool(success)})

    # 4. Extract enabled patches from options
    enabled_in_options: list[str] = []
    if package_name:
        enabled_in_options = get_enabled_patches_from_options(
            options_dir=options_dir,
            package_name=package_name,
            options_file=options_file,
        )

    applied_set = set(applied_patches)
    failed_set = {fp["name"] for fp in failed_patches}

    # Build alias group lookup: group_name -> set(patch_names)
    patch_aliases = patch_aliases or {}
    alias_groups: dict[str, set[str]] = {}
    for p_name, g_name in patch_aliases.items():
        alias_groups.setdefault(g_name, set()).add(p_name)

    # 5. Classify omitted enabled patches into superseded vs unapplied
    superseded_patches: list[dict[str, str]] = []
    unapplied_patches: list[dict[str, str | None]] = []

    for name in enabled_in_options:
        if name in applied_set or name in failed_set:
            continue

        alias_group = patch_aliases.get(name)
        partner_applied = None
        if alias_group:
            all_in_group = alias_groups.get(alias_group, set())
            for partner in all_in_group:
                if partner != name and partner in applied_set:
                    partner_applied = partner
                    break

        if partner_applied:
            superseded_patches.append({
                "name": name,
                "alias_group": alias_group or "",
                "applied_as": partner_applied,
            })
        else:
            reason = unapplied_reasons.get(name) if unapplied_reasons else None
            unapplied_patches.append({
                "name": name,
                "reason": reason,
            })

    # Legacy field maintained strictly for backward compatibility
    legacy_unsupported = [up["name"] for up in unapplied_patches]

    # Build factual summary
    if enabled_in_options:
        count_enabled = len(enabled_in_options)
        count_applied = len(applied_patches)
        count_unapplied = len(unapplied_patches)
        count_superseded = len(superseded_patches)
        count_failed = len(failed_patches)

        if count_unapplied == 0 and count_failed == 0 and count_superseded == 0:
            summary = f"All {count_applied} enabled patches applied"
        else:
            parts = [f"{count_enabled} enabled patches: {count_applied} applied"]
            if count_unapplied > 0:
                parts.append(f"{count_unapplied} not applied")
            if count_superseded > 0:
                parts.append(f"{count_superseded} alias resolved")
            if count_failed > 0:
                parts.append(f"{count_failed} explicitly failed")
            summary = ", ".join(parts)
    elif applied_patches:
        count_applied = len(applied_patches)
        summary = f"{count_applied} patch{'es' if count_applied != 1 else ''} applied"
    else:
        summary = "Patch details unavailable"

    return {
        "available": True,
        "summary": summary,
        "applied_patches": applied_patches,
        "failed_patches": failed_patches,
        "superseded_patches": superseded_patches,
        "unapplied_patches": unapplied_patches,
        "unsupported_patches": legacy_unsupported,
        "enabled_in_options": enabled_in_options,
        "steps": steps,
        "raw_json": json.dumps(data, indent=2),
        "result_file": result_file,
    }


def format_file_size(size_bytes: int) -> str:
    """Formats bytes into human-readable size string."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}" if unit in ["MB", "GB"] else f"{size_bytes} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def format_duration(duration: str | float | int | None) -> str:
    """
    Formats execution duration if supplied.
    Returns 'N/A' if no duration is provided.
    """
    if duration is None or duration == "":
        return "N/A"
    if isinstance(duration, str):
        return duration.strip()
    if isinstance(duration, (int, float)):
        total_sec = int(duration)
        mins, secs = divmod(total_sec, 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            return f"{hours}h {mins}m {secs}s"
        if mins > 0:
            return f"{mins}m {secs}s"
        return f"{secs}s"
    return "N/A"


def calculate_sha256(file_path: Path) -> str:
    """Calculates SHA-256 hex digest of a file in 64KB blocks."""
    sha = hashlib.sha256()
    with file_path.open("rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


# ---------------------------------------------------------------------------
# Attempt Grouping Helpers
# ---------------------------------------------------------------------------

def group_attempts_by_version(attempts: list[dict]) -> dict[str, list[dict]]:
    """
    Groups attempt dictionaries by target version for clean visual display.
    """
    grouped: dict[str, list[dict]] = {}
    for att in attempts:
        raw_ver = att.get("version") or att.get("target_version")
        if isinstance(raw_ver, (tuple, list)) and len(raw_ver) > 0:
            ver = str(raw_ver[0])
        elif raw_ver:
            ver = str(raw_ver)
        else:
            ver = "Unknown version"
        grouped.setdefault(ver, []).append(att)
    return grouped


def resolve_winning_iteration(raw_val: dict, attempts: list[dict]) -> tuple[str, str]:
    """
    Determines the winning strategy and attempt index for a successful build.
    Returns (short_badge_text, full_display_text).
    e.g. ('Strategy 1 • Attempt 1', 'Strategy 1 (All Patches) • Attempt 1 (Target Version)')
    """
    explicit_strategy = raw_val.get("strategy") or raw_val.get("run")
    explicit_attempt = raw_val.get("attempt") or raw_val.get("attempt_index")

    if explicit_strategy is not None and explicit_attempt is not None:
        strat_num = int(explicit_strategy) if str(explicit_strategy).isdigit() else 1
        att_num = int(explicit_attempt) if str(explicit_attempt).isdigit() else 1
        strat_short = format_strategy_name(strat_num, short=True)
        strat_long = format_strategy_name(strat_num, short=False)
        return (f"{strat_short} • Attempt {att_num}", f"{strat_long} • Attempt {att_num}")

    # Deduce from prior failed attempts
    if not attempts:
        return ("Strategy 1 • Attempt 1", "Strategy 1 (All Patches) • Attempt 1 (Target Version)")

    # Count prior attempts on Strategy 1 vs Strategy 2
    strat1_prior = sum(1 for a in attempts if str(a.get("run", "1")) in ("1", "force", "all"))
    strat2_prior = sum(1 for a in attempts if str(a.get("run", "1")) in ("2", "fallback", "compat"))

    if str(explicit_strategy) in ("2", "fallback", "compat"):
        winning_strat = 2
        winning_att = strat2_prior + 1
        desc = "Fallback Pass"
    elif str(explicit_strategy) in ("1", "force", "all"):
        winning_strat = 1
        winning_att = strat1_prior + 1
        desc = "Target Version" if winning_att == 1 else "Backup Version"
    else:
        # If strategy not explicitly given: if any strat2 failures occurred, we must be in strat2
        if strat2_prior > 0:
            winning_strat = 2
            winning_att = strat2_prior + 1
            desc = "Fallback Pass"
        else:
            winning_strat = 1
            winning_att = strat1_prior + 1
            desc = "Backup Version"

    strat_short = format_strategy_name(winning_strat, short=True)
    strat_long = format_strategy_name(winning_strat, short=False)
    return (f"{strat_short} • Attempt {winning_att}", f"{strat_long} • Attempt {winning_att} ({desc})")


def resolve_package_configured_repos(pkg_name: str, config: dict) -> list[str]:
    """
    Returns the configured target/scanned repos for a specific package,
    supporting both new packages schema and legacy apps schema.
    """
    for pkg in config.get("packages") or []:
        if pkg and isinstance(pkg, dict) and (pkg.get("package_name") == pkg_name or pkg.get("package") == pkg_name):
            repos = pkg.get("repos") or []
            return [clean_repo_name(r) for r in repos if r]

    # Backward compatibility with legacy config schema
    global_repos = [clean_repo_name(r) for r in (config.get("patch_repos") or []) if r]
    for app in config.get("apps") or []:
        if app and isinstance(app, dict) and app.get("package") == pkg_name:
            raw_override = app.get("override_repos") or app.get("overide_repo")
            raw_ignore = app.get("ignore_repos") or []
            overrides = [raw_override] if isinstance(raw_override, str) else list(raw_override or [])
            ignores = set(clean_repo_name(r) for r in ([raw_ignore] if isinstance(raw_ignore, str) else list(raw_ignore or [])) if r)
            if overrides:
                targets = [clean_repo_name(r) for r in overrides if r]
                return [r for r in targets if r not in ignores]
            elif ignores:
                return [r for r in global_repos if r not in ignores]
    return global_repos


def resolve_package_patch_aliases(pkg_name: str, config: dict) -> dict[str, str]:
    """
    Returns a mapping of alias names to canonical group names for a package from config.yaml.
    """
    alias_map: dict[str, str] = {}
    for pkg in config.get("packages") or []:
        if pkg and isinstance(pkg, dict) and (pkg.get("package_name") == pkg_name or pkg.get("package") == pkg_name):
            patch_aliases = pkg.get("patch_aliases") or []
            for aliase in patch_aliases:
                if not aliase or not isinstance(aliase, dict):
                    continue
                canonical_name = aliase.get("name")
                aliases = aliase.get("aliases") or []
                for al in aliases:
                    if al:
                        alias_map[al] = canonical_name
            return alias_map

    legacy_aliases = config.get("app_aliases", {}).get(pkg_name)
    if isinstance(legacy_aliases, dict):
        return legacy_aliases

    return {}


# ---------------------------------------------------------------------------
# Email Content Generation
# ---------------------------------------------------------------------------

def assemble_html_document(
    subject: str,
    badge_bg: str,
    badge_border: str,
    badge_dot: str,
    badge_color: str,
    badge_text: str,
    now_str: str,
    host_display: str,
    total_success: int,
    total_failures: int,
    succeeded_chips_html: str,
    failed_chips_html: str,
    duration_str: str,
    general_flags_section_html: str,
    failures_section_html: str,
    success_section_html: str,
    log_section_html: str,
    banner_html: str = "",
    bottom_banner_html: str = "",
    web_report_url: str | None = None,
    web_report_endpoints: list[dict] | None = None,
    security_badge_text: str = "Tailscale Funnel",
) -> str:
    """
    Assembles the complete responsive HTML document in Morphe Obsidian Cyber Synthetics styling.
    """
    if web_report_endpoints and len(web_report_endpoints) > 1:
        links = []
        for ep in web_report_endpoints:
            if ep.get("url"):
                col = "#38bdf8" if ep.get("id") == "cloudflare" else ("#a78bfa" if ep.get("id") == "pangolin" else "#38bdf8")
                links.append(f'<a href="{ep["url"]}" target="_blank" style="font-size: 12px; color: {col}; text-decoration: none; font-weight: 600;">{ep.get("label", "Report")}</a>')
        web_link_hdr = (
            f'<span style="font-size: 12px; color: #475569; padding: 0 4px;">&bull;</span>'
            f'<span style="font-size: 12px; color: #94a3b8; font-weight: 600;">🌐 Reports: </span>'
            + ' <span style="font-size: 11px; color: #475569; padding: 0 2px;">|</span> '.join(links)
        )
    elif web_report_url:
        web_link_hdr = (
            f'<span style="font-size: 12px; color: #475569; padding: 0 4px;">&bull;</span>'
            f'<a href="{web_report_url}" target="_blank" style="font-size: 12px; color: #38bdf8; text-decoration: none; font-weight: 600;">🌐 Web Report &rarr;</a>'
        )
    else:
        web_link_hdr = ""

    return f"""<!DOCTYPE html>
<html lang="en" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
  <meta charset="utf-8">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="dark">
  <meta name="supported-color-schemes" content="dark">
  <title>{subject}</title>
  <!--[if mso]>
  <noscript>
    <xml>
      <o:OfficeDocumentSettings>
        <o:PixelsPerInch>96</o:PixelsPerInch>
      </o:OfficeDocumentSettings>
    </xml>
  </noscript>
  <style type="text/css">
    body, table, td, span, a, p {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif !important; }}
    .btn-gradient {{ background-color: #38bdf8 !important; }}
  </style>
  <![endif]-->
  <style type="text/css">
    body, p, h1, h2, h3, div, table, td {{
      margin: 0;
      padding: 0;
    }}
    body {{
      -webkit-text-size-adjust: 100%;
      -ms-text-size-adjust: 100%;
      background-color: #0c0e14;
    }}
    table, td {{
      mso-table-lspace: 0pt;
      mso-table-rspace: 0pt;
      border-collapse: collapse;
    }}
    img {{
      -ms-interpolation-mode: bicubic;
      border: 0;
      line-height: 100%;
      outline: none;
      text-decoration: none;
      display: block;
    }}
    @media only screen and (max-width: 640px) {{
      .email-container {{
        width: 100% !important;
        max-width: 100% !important;
      }}
      .metric-col {{
        display: block !important;
        width: 100% !important;
        margin-bottom: 8px !important;
        box-sizing: border-box !important;
      }}
      .stack-mobile {{
        display: block !important;
        width: 100% !important;
        text-align: left !important;
      }}
      .stack-mobile-right {{
        display: block !important;
        width: 100% !important;
        text-align: left !important;
        margin-top: 6px !important;
      }}
      .content-padding {{
        padding-left: 16px !important;
        padding-right: 16px !important;
      }}
    }}
  </style>
</head>
<body style="margin: 0; padding: 0; background-color: #0c0e14; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased; color: #f1f5f9;">

  <!-- Preheader text (hidden in display, shown in inbox snippet) -->
  <div style="display: none; font-size: 1px; color: #0c0e14; line-height: 1px; max-height: 0px; max-width: 0px; opacity: 0; overflow: hidden; mso-hide: all;">
    Morphe Patcher: {total_success} succeeded, {total_failures} failed &zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;
  </div>

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#0c0e14" style="background-color: #0c0e14; table-layout: fixed;">
    <tr>
      <td align="center" style="padding: 24px 12px 36px 12px;">

        <!--[if (gte mso 9)|(IE)]>
        <table role="presentation" width="600" align="center" cellpadding="0" cellspacing="0" border="0">
        <tr>
        <td>
        <![endif]-->
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="email-container" style="max-width: 620px; width: 100%; margin: 0 auto; background-color: #10121a; border: 1px solid #1f2330; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.7);">

          <!-- Top Brand Header Block -->
          <tr>
            <td style="padding: 26px 28px 18px 28px;" class="content-padding">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="border-bottom: 1px solid #1f2330; padding-bottom: 16px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                      <tr>
                        <td class="stack-mobile">
                          <h1 style="font-size: 21px; font-weight: 800; color: #ffffff; letter-spacing: -0.3px; margin: 0; line-height: 1.25;">
                            Morphe Patcher Build Report
                          </h1>
                        </td>
                        <td align="right" class="stack-mobile-right" valign="middle">
                          <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="background-color: {badge_bg}; border: 1px solid {badge_border}; border-radius: 20px;">
                            <tr>
                              <td style="padding: 3px 9px;">
                                <span style="display: inline-block; width: 6px; height: 6px; border-radius: 50%; background-color: {badge_dot}; vertical-align: middle; margin-right: 4px;"></span>
                                <span style="font-size: 11px; font-weight: 700; color: {badge_color}; text-transform: uppercase; letter-spacing: 0.4px;">{badge_text}</span>
                              </td>
                            </tr>
                          </table>
                        </td>
                      </tr>
                      <tr>
                        <td colspan="2" style="padding-top: 4px;">
                          <span style="font-size: 12px; color: #94a3b8; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;">{now_str}</span>
                          <span style="font-size: 12px; color: #475569; padding: 0 4px;">&bull;</span>
                          <span style="font-size: 12px; color: #94a3b8;">Funnel Host: <code style="color: #38bdf8; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; background-color: #191b22; padding: 1px 5px; border-radius: 4px; border: 1px solid #232a3e;">{host_display}</code></span>
                          {web_link_hdr}
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- Executive Metric Summary (3-Column Layout) -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top: 20px;">
                <tr>
                  <!-- Metric 1: Succeeded -->
                  <td width="32%" class="metric-col" valign="top" style="padding: 0 4px 0 0;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #191b22; border: 1px solid #232a3e; border-radius: 10px; border-left: 3px solid #10b981;">
                      <tr>
                        <td style="padding: 10px 12px;">
                          <div style="font-size: 11px; font-weight: 700; color: #34d399; text-transform: uppercase; letter-spacing: 0.5px;">
                            <span style="display: inline-block; width: 6px; height: 6px; border-radius: 50%; background-color: #10b981; vertical-align: middle; margin-right: 4px;"></span>Succeeded
                          </div>
                          <div style="font-size: 20px; font-weight: 800; color: #ffffff; margin-top: 4px;">
                            {total_success} <span style="font-size: 12px; font-weight: 500; color: #94a3b8;">app{'s' if total_success != 1 else ''}</span>
                          </div>
                          {succeeded_chips_html}
                        </td>
                      </tr>
                    </table>
                  </td>

                  <!-- Metric 2: Failed -->
                  <td width="32%" class="metric-col" valign="top" style="padding: 0 2px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #191b22; border: 1px solid #232a3e; border-radius: 10px; border-left: 3px solid #ef4444;">
                      <tr>
                        <td style="padding: 10px 12px;">
                          <div style="font-size: 11px; font-weight: 700; color: #f87171; text-transform: uppercase; letter-spacing: 0.5px;">
                            <span style="display: inline-block; width: 6px; height: 6px; border-radius: 50%; background-color: #ef4444; vertical-align: middle; margin-right: 4px;"></span>Failed
                          </div>
                          <div style="font-size: 20px; font-weight: 800; color: #ffffff; margin-top: 4px;">
                            {total_failures} <span style="font-size: 12px; font-weight: 500; color: #94a3b8;">app{'s' if total_failures != 1 else ''}</span>
                          </div>
                          {failed_chips_html}
                        </td>
                      </tr>
                    </table>
                  </td>

                  <!-- Metric 3: Duration -->
                  <td width="36%" class="metric-col" valign="top" style="padding: 0 0 0 4px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #191b22; border: 1px solid #232a3e; border-radius: 10px; border-left: 3px solid #38bdf8;">
                      <tr>
                        <td style="padding: 10px 12px;">
                          <div style="font-size: 11px; font-weight: 700; color: #38bdf8; text-transform: uppercase; letter-spacing: 0.5px;">
                            <span style="display: inline-block; width: 6px; height: 6px; border-radius: 50%; background-color: #38bdf8; vertical-align: middle; margin-right: 4px;"></span>Duration
                          </div>
                          <div style="font-size: 20px; font-weight: 800; color: #ffffff; margin-top: 4px;">
                            {duration_str}
                          </div>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

            </td>
          </tr>

          <!-- BUILD CONFIGURATION & GENERAL FLAGS BAR -->
          {general_flags_section_html}

          <!-- OPTIONAL TOP BANNER -->
          {banner_html}

          <!-- Divider Line -->
          <tr>
            <td style="padding: 12px 28px 0 28px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr><td height="1" style="background-color: #1f2330; font-size: 0; line-height: 0;">&nbsp;</td></tr>
              </table>
            </td>
          </tr>

          <!-- PIPELINE FAILURES SECTION (IF ANY) -->
          {failures_section_html}

          <!-- READY FOR DOWNLOAD SECTION (IF ANY) -->
          {success_section_html}

          <!-- OPTIONAL BOTTOM BANNER -->
          {bottom_banner_html}

          <!-- EXECUTION LOG SECTION (IF PROVIDED) -->
          {log_section_html}

          <!-- Footer Section -->
          <tr>
            <td style="background-color: #0c0e14; border-top: 1px solid #1f2330; padding: 22px 28px 26px 28px; text-align: center;" class="content-padding">
              <div style="font-size: 12px; color: #94a3b8; line-height: 1.6;">
                Delivered by <strong style="color: #f1f5f9;">Morphe Patcher Dispatcher</strong> &bull; Secured via <strong style="color: #f1f5f9;">{security_badge_text}</strong>
              </div>
              <div style="margin-top: 6px; font-size: 12px; color: #64748b;">
                <span style="display: inline-block; width: 10px; height: 5px; border-radius: 2.5px; background: linear-gradient(90deg, #38bdf8 50%, #8b5cf6 50%); vertical-align: middle; margin-right: 4px;"></span>
                Powered by <strong style="color: #cbd5e1;">Morphe</strong> &bull; <a href="https://morphe.software" style="color: #38bdf8; text-decoration: none;">morphe.software</a>
              </div>
            </td>
          </tr>

        </table>
        <!--[if (gte mso 9)|(IE)]>
        </td>
        </tr>
        </table>
        <![endif]-->

      </td>
    </tr>
  </table>

</body>
</html>
"""


def generate_email_content(
    patch_success: dict[str, Path | dict],
    failures: dict[str, dict] | None,
    config: dict,
    project_root: Path | None = None,
    log_content: str | Path | None = None,
    duration: str | float | int | None = None,
    build_flags: dict | None = None,
) -> tuple[str, str, str, list[Path]]:
    """
    Generates Subject, Plain Text body, and HTML body with Obsidian Cyber Synthetics styling.
    """
    project_root = project_root or config.get("project_root") or Path(__file__).resolve().parent.parent
    email_conf = config.get("email") or {}
    patched_dir = (project_root / "apps" / "patched").resolve()
    raw_opt_loc = config.get("options_location")
    if raw_opt_loc:
        opt_path = Path(raw_opt_loc)
        options_dir = opt_path if opt_path.is_absolute() else (project_root / opt_path).resolve()
    else:
        options_dir = (project_root / "tools" / "automorph-data" / "options").resolve()
        if not options_dir.exists() and (project_root / "options").exists():
            options_dir = (project_root / "options").resolve()
    calc_checksum = email_conf.get("calculate_checksum", email_conf.get("include_checksum", False))
    attach_json = email_conf.get("attach_result_json", False)

    raw_state_loc = config.get("state_location")
    if raw_state_loc:
        s_path = Path(raw_state_loc)
        state_dir = s_path if s_path.is_absolute() else (project_root / s_path).resolve()
    else:
        state_dir = (project_root / "tools" / "automorph-data" / "state").resolve()
        if not state_dir.exists() and (project_root / "tools" / "state").exists():
            state_dir = (project_root / "tools" / "state").resolve()
    reports_dir = (state_dir / "reports").resolve()

    # Resolve global build configuration & flags (from parameter or config.yaml)
    default_arch = config.get("architecture", "arm64-v8a")
    global_arch = (build_flags.get("architecture") if build_flags else None) or default_arch
    striplibs_val = (build_flags.get("striplibs") if build_flags else None)
    if striplibs_val is None:
        striplibs_val = config.get("striplibs", False)
    low_spec_val = (build_flags.get("low_spec_mode") if build_flags else None)
    if low_spec_val is None:
        low_spec_val = config.get("low_spec_mode", False)

    # Collect configured patch repos across packages as default scanned candidates
    configured_repos = []
    for pkg in config.get("packages") or []:
        if pkg and isinstance(pkg, dict):
            for r in pkg.get("repos") or []:
                if r:
                    c = clean_repo_name(r)
                    if c not in configured_repos:
                        configured_repos.append(c)
    if not configured_repos and config.get("patch_repos"):
        configured_repos = [clean_repo_name(r) for r in config.get("patch_repos") if r]

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    failures = failures or {}
    duration_str = format_duration(duration)

    # Resolve active tunnel endpoints & branding (crash-proof)
    endpoints = resolve_tunnel_endpoints(config)
    ep_ids = {ep.get("id") for ep in endpoints if isinstance(ep, dict)}
    if "cloudflare" in ep_ids and "pangolin" in ep_ids:
        security_badge_text = "Cloudflare & Pangolin Tunnels"
    elif "cloudflare" in ep_ids:
        security_badge_text = "Cloudflare Tunnel"
    elif "pangolin" in ep_ids:
        security_badge_text = "Pangolin Tunnel"
    elif "tailscale" in ep_ids:
        security_badge_text = "Tailscale Funnel"
    else:
        security_badge_text = "Local Origin Server"

    # Extract clean host name for display
    valid_eps = [ep for ep in endpoints if isinstance(ep, dict) and ep.get("base_url")]
    if len(valid_eps) > 1:
        host_display = " • ".join(
            urlparse(ep["base_url"]).netloc or ep["base_url"].replace("https://", "").replace("http://", "")
            for ep in valid_eps
        )
    elif valid_eps:
        parsed_url = urlparse(valid_eps[0]["base_url"])
        host_display = parsed_url.netloc or valid_eps[0]["base_url"].replace("https://", "").replace("http://", "")
    else:
        host_display = "localhost:8080"

    # Full HTML report file path (stored in persistent state/reports) & Funnel/Tunnel URLs
    report_filename = "build_report.html"
    report_path = (reports_dir / report_filename).resolve()
    web_report_endpoints = []
    for ep in endpoints:
        b_url = ep.get("base_url")
        if b_url:
            web_report_endpoints.append({
                "id": ep.get("id", "portal"),
                "label": ep.get("label", "Web Portal"),
                "badge": ep.get("badge", ep.get("label", "Portal")),
                "icon": ep.get("icon", "🌐"),
                "color": ep.get("color", "#38bdf8"),
                "url": f"{b_url.rstrip('/')}/",
            })
    web_report_url = web_report_endpoints[0]["url"] if web_report_endpoints else None

    # 1. normalise and gather data for Successful Apps
    success_records = []
    attachments: list[Path] = []

    for pkg_name, raw_val in patch_success.items():
        if isinstance(raw_val, dict):
            dest_raw = raw_val.get("dest") or raw_val.get("path")
            attempts = list(raw_val.get("attempts") or [])
            options_file_raw = raw_val.get("options_file")
            options_file = Path(options_file_raw) if options_file_raw else None
            patch_aliases = raw_val.get("patch_aliases") or resolve_package_patch_aliases(pkg_name, config)
            unapplied_reasons = raw_val.get("unapplied_reasons")
            arch = raw_val.get("arch") or global_arch

            pkg_configured_repos = resolve_package_configured_repos(pkg_name, config)

            # Extract repository metadata (can be single str, list, or set)
            raw_scanned = raw_val.get("scanned_repos") or raw_val.get("repos_scanned")
            raw_applied = raw_val.get("applied_repos") or raw_val.get("repos_applied") or raw_val.get("repos")

            if raw_scanned:
                cleaned_scanned = [clean_repo_name(r) for r in (list(raw_scanned) if isinstance(raw_scanned, (list, set)) else [raw_scanned]) if r]
                # If caller passed unfiltered global list, narrow to package-specific configured target repos
                if set(cleaned_scanned) == set(configured_repos) and set(pkg_configured_repos) != set(configured_repos):
                    scanned_repos = list(pkg_configured_repos)
                else:
                    scanned_repos = cleaned_scanned
            else:
                scanned_repos = list(pkg_configured_repos)

            if raw_applied:
                cleaned_applied = [clean_repo_name(r) for r in (list(raw_applied) if isinstance(raw_applied, (list, set)) else [raw_applied]) if r]
                if set(cleaned_applied) == set(configured_repos) and set(pkg_configured_repos) != set(configured_repos):
                    applied_repos = list(pkg_configured_repos)
                else:
                    applied_repos = cleaned_applied
            else:
                applied_repos = list(scanned_repos)
        else:
            dest_raw = raw_val
            attempts = []
            options_file = None
            patch_aliases = resolve_package_patch_aliases(pkg_name, config)
            unapplied_reasons = None
            arch = global_arch
            pkg_configured_repos = resolve_package_configured_repos(pkg_name, config)
            scanned_repos = list(pkg_configured_repos)
            applied_repos = list(pkg_configured_repos)
            raw_val = {}

        if not dest_raw:
            continue

        resolved_apk = Path(dest_raw).resolve()
        file_exists = resolved_apk.is_file()
        file_size_str = format_file_size(resolved_apk.stat().st_size) if file_exists else "Unknown size"
        checksum_str = calculate_sha256(resolved_apk) if (file_exists and calc_checksum) else None

        version_str = resolved_apk.parent.name if resolved_apk.parent else "Unknown"
        download_urls = {}
        for ep in endpoints:
            b_url = ep.get("base_url")
            if not b_url:
                continue
            try:
                rel_apk = resolved_apk.relative_to(patched_dir)
                d_url = f"{b_url.rstrip('/')}/files/{rel_apk.as_posix()}"
            except Exception:
                d_url = f"{b_url.rstrip('/')}/files/{resolved_apk.name}"
            download_urls[ep["id"]] = {
                "id": ep["id"],
                "label": ep["label"],
                "badge": ep.get("badge", ep.get("label", ep["id"])),
                "icon": ep.get("icon", "⚡"),
                "color": ep.get("color", "#0284c7"),
                "url": d_url,
            }
        download_url = next(iter(download_urls.values()))["url"] if download_urls else None
        patch_info = inspect_patch_result(
            resolved_apk,
            options_dir=options_dir,
            package_name=pkg_name,
            patch_aliases=patch_aliases,
            unapplied_reasons=unapplied_reasons,
            options_file=options_file,
        )

        if attach_json and patch_info.get("result_file"):
            attachments.append(patch_info["result_file"])

        winning_badge, winning_full = resolve_winning_iteration(raw_val, attempts)

        success_records.append({
            "package": pkg_name,
            "version": version_str,
            "arch": arch,
            "filename": resolved_apk.name,
            "file_size": file_size_str,
            "checksum": checksum_str,
            "download_url": download_url,
            "download_urls": download_urls,
            "patch_info": patch_info,
            "attempts": attempts,
            "scanned_repos": scanned_repos,
            "applied_repos": applied_repos,
            "winning_badge": winning_badge,
            "winning_full": winning_full,
        })

    # 2. Gather data for Severe Pipeline Failures
    failure_records = []
    for pkg_name, fail_info in failures.items():
        raw_targets = fail_info.get("target_versions") or []
        target_versions = [
            str(t[0]) if isinstance(t, (tuple, list)) and len(t) > 0 else str(t)
            for t in (list(raw_targets) if isinstance(raw_targets, (list, tuple, set)) else [raw_targets])
            if t is not None
        ]
        arch = fail_info.get("arch") or global_arch
        attempts = fail_info.get("attempts") or []

        pkg_configured_repos = resolve_package_configured_repos(pkg_name, config)

        raw_scanned = fail_info.get("scanned_repos") or fail_info.get("repos_scanned")
        if raw_scanned:
            cleaned_scanned = [clean_repo_name(r) for r in (list(raw_scanned) if isinstance(raw_scanned, (list, set)) else [raw_scanned]) if r]
            if set(cleaned_scanned) == set(configured_repos) and set(pkg_configured_repos) != set(configured_repos):
                scanned_repos = list(pkg_configured_repos)
            else:
                scanned_repos = cleaned_scanned
        else:
            scanned_repos = list(pkg_configured_repos)

        raw_applied = fail_info.get("applied_repos") or fail_info.get("repos_applied") or fail_info.get("repos")
        if raw_applied:
            cleaned_applied = [clean_repo_name(r) for r in (list(raw_applied) if isinstance(raw_applied, (list, set)) else [raw_applied]) if r]
            if set(cleaned_applied) == set(configured_repos) and set(pkg_configured_repos) != set(configured_repos):
                attempted_repos = list(pkg_configured_repos)
            else:
                attempted_repos = cleaned_applied
        else:
            attempted_repos = list(scanned_repos)

        failure_records.append({
            "package": pkg_name,
            "target_versions": target_versions,
            "arch": arch,
            "attempts": attempts,
            "scanned_repos": scanned_repos,
            "attempted_repos": attempted_repos,
            "grouped_attempts": group_attempts_by_version(attempts),
        })

    # Optional external log string
    raw_log_str = None
    if isinstance(log_content, Path) and log_content.is_file():
        attachments.append(log_content)
        try:
            raw_log_str = log_content.read_text(encoding="utf-8")
        except Exception:
            raw_log_str = None
    elif isinstance(log_content, str) and log_content.strip():
        raw_log_str = log_content.strip()

    # 3. Determine Overall Status & Subject Line
    prefix = email_conf.get("subject_prefix", "[Morphe Patcher]")
    total_success = len(success_records)
    total_failures = len(failure_records)

    total_unapplied = sum(len(app["patch_info"]["unapplied_patches"]) for app in success_records)
    total_explicit_failed = sum(len(app["patch_info"]["failed_patches"]) for app in success_records)

    if total_failures > 0:
        if total_success == 0:
            subject = f"{prefix} ❌ Build Failed: All {total_failures} App{'s' if total_failures != 1 else ''} Failed"
            badge_text = "Build Failed"
            badge_bg = "rgba(239, 68, 68, 0.15)"
            badge_border = "rgba(239, 68, 68, 0.35)"
            badge_dot = "#ef4444"
            badge_color = "#fca5a5"
        else:
            subject = f"{prefix} ⚠️ Build Report: {total_success} Succeeded, {total_failures} Pipeline Failure{'s' if total_failures != 1 else ''}"
            badge_text = "Partial Failure"
            badge_bg = "rgba(245, 158, 11, 0.12)"
            badge_border = "rgba(245, 158, 11, 0.35)"
            badge_dot = "#f59e0b"
            badge_color = "#fbbf24"
    elif total_explicit_failed > 0:
        subject = f"{prefix} ⚠️ {total_success} App{'s' if total_success != 1 else ''} Patched (Patch Errors Reported)"
        badge_text = "Patch Errors"
        badge_bg = "rgba(245, 158, 11, 0.12)"
        badge_border = "rgba(245, 158, 11, 0.35)"
        badge_dot = "#f59e0b"
        badge_color = "#fbbf24"
    elif total_unapplied > 0:
        subject = f"{prefix} ⚠️ {total_success} App{'s' if total_success != 1 else ''} Patched ({total_unapplied} Not Applied)"
        badge_text = "Partial Patches"
        badge_bg = "rgba(245, 158, 11, 0.12)"
        badge_border = "rgba(245, 158, 11, 0.35)"
        badge_dot = "#f59e0b"
        badge_color = "#fbbf24"
    elif total_success == 0:
        subject = f"{prefix} ℹ️ All Configured Packages Up to Date"
        badge_text = "Up to Date"
        badge_bg = "rgba(16, 185, 129, 0.12)"
        badge_border = "rgba(16, 185, 129, 0.35)"
        badge_dot = "#10b981"
        badge_color = "#34d399"
    else:
        subject = f"{prefix} 🚀 {total_success} App{'s' if total_success != 1 else ''} Patched Successfully"
        badge_text = "All Passed"
        badge_bg = "rgba(16, 185, 129, 0.12)"
        badge_border = "rgba(16, 185, 129, 0.35)"
        badge_dot = "#10b981"
        badge_color = "#34d399"

    # Build Chips for Top Summary Boxes
    if success_records:
        succeeded_chips = "".join(
            f'<span style="display: inline-block; background-color: #162026; border: 1px solid #23373e; border-radius: 10px; padding: 2px 8px; margin: 2px 3px 2px 0; font-size: 11px; line-height: 16px; color: #cbd5e1; word-break: break-all; white-space: normal;">'
            f'<span style="color: #34d399; font-weight: bold; margin-right: 4px;">&bull;</span>{html.escape(app["package"])}</span>'
            for app in success_records
        )
        succeeded_chips_html = f'<div style="margin-top: 8px; line-height: 20px;">{succeeded_chips}</div>'
    else:
        succeeded_chips_html = '<div style="margin-top: 6px; font-size: 11px; color: #64748b;">None</div>'

    if failure_records:
        failed_chips = "".join(
            f'<span style="display: inline-block; background-color: #241618; border: 1px solid #4a2327; border-radius: 10px; padding: 2px 8px; margin: 2px 3px 2px 0; font-size: 11px; line-height: 16px; color: #fca5a5; word-break: break-all; white-space: normal;">'
            f'<span style="color: #ef4444; font-weight: bold; margin-right: 4px;">&bull;</span>{html.escape(fail["package"])}</span>'
            for fail in failure_records
        )
        failed_chips_html = f'<div style="margin-top: 8px; line-height: 20px;">{failed_chips}</div>'
    else:
        failed_chips_html = '<div style="margin-top: 6px; font-size: 11px; color: #64748b;">None</div>'

    succeeded_names_str = f" ({', '.join(app['package'] for app in success_records)})" if success_records else ""
    failed_names_str = f" ({', '.join(fail['package'] for fail in failure_records)})" if failure_records else ""

    # Build Flags Display Elements
    striplibs_display = f"Enabled (kept: {global_arch})" if striplibs_val else "Disabled"
    low_spec_display = "Active (-Xmx1536m)" if low_spec_val else "Standard"

    # -----------------------------------------------------------------------
    # Plain-Text Body
    # -----------------------------------------------------------------------
    text_lines = [
        "============================================================",
        " MORPHE PATCHER - BUILD REPORT",
        "============================================================",
        f"Build Date        : {now_str}",
        f"Host              : {host_display}",
        *(
            [f"Web Report ({ep['label']}): {ep['url']}" for ep in web_report_endpoints]
            if len(web_report_endpoints) > 1
            else ([f"Web Report        : {web_report_url}"] if web_report_url else [])
        ),
        f"Apps Patched      : {total_success}{succeeded_names_str}",
        f"Pipeline Failures : {total_failures}{failed_names_str}",
        f"Duration          : {duration_str}",
        "",
        "BUILD CONFIGURATION & GENERAL FLAGS:",
        f"  Target Arch     : {global_arch}",
        f"  Strip Libs      : {striplibs_display}",
        f"  Low-Spec Mode   : {low_spec_display}",
        "",
    ]

    # Pipeline Failures Section
    if failure_records:
        text_lines.append("------------------------------------------------------------")
        text_lines.append(" SEVERE PIPELINE FAILURES")
        text_lines.append("------------------------------------------------------------")
        for i, fail in enumerate(failure_records, 1):
            targets_str = ", ".join(fail["target_versions"]) if fail["target_versions"] else "None specified"
            scanned_str = ", ".join(fail["scanned_repos"]) if fail["scanned_repos"] else "None"
            attempted_repos_str = ", ".join(fail["attempted_repos"]) if fail["attempted_repos"] else "None"

            text_lines.append(f"[{i}] {fail['package']}")
            text_lines.append(f"    Target Architecture       : {fail['arch']}")
            text_lines.append(f"    Target Versions Attempted : {targets_str}")
            text_lines.append(f"    Scanned Repositories      : {scanned_str}")
            text_lines.append(f"    Attempted Repositories    : {attempted_repos_str}")
            text_lines.append("    Diagnostic History:")

            for ver, att_list in fail["grouped_attempts"].items():
                text_lines.append(f"      * Target v{ver}:")
                for att in att_list:
                    stage = str(att.get("stage", "General")).upper()
                    strat_name = format_strategy_name(att.get("run", 1), short=True)
                    reason = att.get("reason", "Unknown failure")
                    text_lines.append(f"        - [{stage}] ({strat_name}): {reason}")
            text_lines.append("")

    # Successful Builds Section
    if success_records:
        text_lines.append("------------------------------------------------------------")
        text_lines.append(" READY FOR DOWNLOAD (SUCCESSFUL BUILDS)")
        text_lines.append("------------------------------------------------------------")
        for i, app in enumerate(success_records, 1):
            patch_info = app["patch_info"]
            scanned_str = ", ".join(app["scanned_repos"]) if app["scanned_repos"] else "None"
            applied_str = ", ".join(app["applied_repos"]) if app["applied_repos"] else "None"

            text_lines.append(f"[{i}] {app['package']} (v{app['version']})")
            text_lines.append(f"    Architecture              : {app['arch']}")
            text_lines.append(f"    Build Resolution          : {app['winning_full']}")
            text_lines.append(f"    Scanned Repositories      : {scanned_str}")
            text_lines.append(f"    Applied Repositories      : {applied_str}")
            text_lines.append(f"    File: {app['filename']} ({app['file_size']})")
            if app["checksum"]:
                text_lines.append(f"    SHA-256: {app['checksum']}")
            if app.get("download_urls") and len(app["download_urls"]) > 1:
                for ep_id, ep_info in app["download_urls"].items():
                    text_lines.append(f"    Download ({ep_info['label']}): {ep_info['url']}")
            elif app.get("download_url"):
                text_lines.append(f"    Download: {app['download_url']}")
            text_lines.append(f"    Summary: {patch_info['summary']}")

            # Fallback progression
            if app["attempts"]:
                text_lines.append("    Prior Fallback Attempts:")
                for att in app["attempts"]:
                    strat_name = format_strategy_name(att.get("run", 1), short=True)
                    text_lines.append(
                        f"      - Target v{att.get('version')}: {strat_name} ({att.get('stage')}) — {att.get('reason')}"
                    )

            # Applied patches
            if patch_info.get("applied_patches"):
                text_lines.append("    Applied Patches:")
                for ap in patch_info["applied_patches"]:
                    text_lines.append(f"      + {ap}")

            # Superseded / Alias
            if patch_info.get("superseded_patches"):
                text_lines.append("    Alias Resolution (Superseded):")
                for sp in patch_info["superseded_patches"]:
                    text_lines.append(f"      * {sp['name']} (satisfied by '{sp['applied_as']}')")

            # Not applied
            if patch_info.get("unapplied_patches"):
                text_lines.append("    Not Applied:")
                for up in patch_info["unapplied_patches"]:
                    reason_str = f" — {up['reason']}" if up.get("reason") else ""
                    text_lines.append(f"      ~ {up['name']}{reason_str}")

            # Explicitly failed
            if patch_info.get("failed_patches"):
                text_lines.append("    Explicitly Failed Patches:")
                for fp in patch_info["failed_patches"]:
                    text_lines.append(f"      ! {fp['name']}: {fp['reason']}")

            text_lines.append("")

    if raw_log_str:
        text_lines.append("------------------------------------------------------------")
        text_lines.append(" EXECUTION LOG")
        text_lines.append("------------------------------------------------------------")
        text_lines.append(raw_log_str)
        text_lines.append("")

    text_lines.append("============================================================")
    text_body = "\n".join(text_lines)

    # -----------------------------------------------------------------------
    # HTML Body - Morphe Obsidian Cyber Synthetics Template
    # -----------------------------------------------------------------------

    # Build Pipeline Failure Cards & Compact Rows
    failure_cards_html = []
    compact_failure_rows = []
    if failure_records:
        for fail in failure_records:
            attempts_rows = []
            for ver, att_list in fail["grouped_attempts"].items():
                sub_items = []
                for att in att_list:
                    strat_label = format_strategy_name(att.get("run", 1), short=True).upper()
                    stage = str(att.get("stage", "GENERAL")).upper()
                    reason = html.escape(str(att.get("reason", "Unknown failure")))
                    badge_bg_sub = "rgba(239, 68, 68, 0.2)" if "DOWNLOAD" in stage else "rgba(245, 158, 11, 0.2)"
                    badge_color_sub = "#f87171" if "DOWNLOAD" in stage else "#fbbf24"

                    sub_items.append(f"""
                    <div style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; color: #cbd5e1; margin-top: 6px; line-height: 1.4;">
                      <span style="display: inline-block; background-color: {badge_bg_sub}; color: {badge_color_sub}; font-weight: 700; padding: 1px 5px; border-radius: 3px; font-size: 10px;">{stage} &bull; {strat_label}</span>
                      {reason}
                    </div>
                    """)
                sub_items_joined = "".join(sub_items)

                attempts_rows.append(f"""
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #0c0e14; border: 1px solid #231c22; border-left: 3px solid #ef4444; border-radius: 6px; margin-bottom: 8px;">
                  <tr>
                    <td style="padding: 10px 12px;">
                      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                        <tr>
                          <td align="left">
                            <span style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; font-weight: 700; color: #fca5a5;">Target v{ver}</span>
                          </td>
                          <td align="right">
                            <span style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 11px; color: #64748b;">{len(att_list)} Attempt{'s' if len(att_list) != 1 else ''}</span>
                          </td>
                        </tr>
                      </table>
                      {sub_items_joined}
                    </td>
                  </tr>
                </table>
                """)

            attempts_joined = "".join(attempts_rows)
            target_codes = " ".join(
                f'<code style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; color: #e2e8f0; background-color: #0c0e14; padding: 2px 6px; border-radius: 4px; border: 1px solid #1f2330;">v{t}</code>'
                for t in fail["target_versions"]
            ) if fail["target_versions"] else '<span style="color: #64748b;">None specified</span>'

            # Repositories for failure card
            scanned_badges = " ".join(
                f'<span style="display: inline-block; background-color: #191b22; color: #94a3b8; border: 1px solid #232a3e; border-radius: 4px; padding: 1px 7px; margin: 2px 4px 2px 0; font-size: 11px; font-family: ui-monospace, monospace;">{html.escape(r)}</span>'
                for r in fail["scanned_repos"]
            ) if fail["scanned_repos"] else '<span style="color: #64748b; font-size: 11px;">None</span>'

            attempted_repo_badges = " ".join(
                f'<span style="display: inline-block; background-color: #241618; color: #fca5a5; border: 1px solid #4a2327; border-radius: 4px; padding: 1px 7px; margin: 2px 4px 2px 0; font-size: 11px; font-family: ui-monospace, monospace;">{html.escape(r)}</span>'
                for r in fail["attempted_repos"]
            ) if fail["attempted_repos"] else '<span style="color: #64748b; font-size: 11px;">None</span>'

            failure_card = f"""
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #141720; border: 1px solid #2b232a; border-radius: 12px; overflow: hidden; border-top: 2px solid #ef4444; margin-bottom: 16px;">
              <tr>
                <td style="padding: 16px 18px;">
                  <!-- Package Title Bar with permanently visible ARCH tag -->
                  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                    <tr>
                      <td class="stack-mobile" align="left" valign="middle">
                        <span style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 15px; font-weight: 700; color: #f1f5f9;">{fail['package']}</span>
                        <span style="display: inline-block; background-color: rgba(148, 163, 184, 0.12); color: #cbd5e1; border: 1px solid #232a3e; font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 4px; margin-left: 6px; font-family: ui-monospace, monospace;">{fail['arch']}</span>
                        <span style="display: inline-block; background-color: rgba(239, 68, 68, 0.15); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.3); font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 4px; margin-left: 6px; text-transform: uppercase;">BUILD FAILED</span>
                      </td>
                    </tr>
                  </table>

                  <div style="font-size: 12px; color: #94a3b8; margin-top: 10px;">
                    Targets attempted: {target_codes}
                  </div>

                  <!-- Repository Sources Row -->
                  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #0c0e14; border: 1px solid #1f2330; border-radius: 6px; margin-top: 10px;">
                    <tr>
                      <td style="padding: 10px 12px;">
                        <div style="font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">
                          Repository Tracking
                        </div>
                        <div style="font-size: 11px; line-height: 20px;">
                          <span style="color: #64748b; font-weight: 600; margin-right: 6px;">Target Repos:</span>{attempted_repo_badges}
                        </div>
                        <div style="font-size: 11px; line-height: 20px; margin-top: 2px;">
                          <span style="color: #64748b; font-weight: 600; margin-right: 6px;">Scanned Repos:</span>{scanned_badges}
                        </div>
                      </td>
                    </tr>
                  </table>

                  <div style="font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.6px; margin-top: 14px; margin-bottom: 8px;">
                    Failure Diagnostics
                  </div>

                  {attempts_joined}
                </td>
              </tr>
            </table>
            """
            failure_cards_html.append(failure_card)

            # Compact failure row
            first_att = fail["attempts"][0] if fail.get("attempts") else {}
            fail_summary_reason = html.escape(str(first_att.get("reason") or "Patching could not be completed"))
            fail_stage = str(first_att.get("stage") or "General").upper()
            target_vers = ", ".join(f"v{v}" for v in fail["target_versions"]) if fail.get("target_versions") else "None specified"

            compact_fail = f"""
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #141720; border: 1px solid #2b232a; border-left: 3px solid #ef4444; border-radius: 8px; margin-bottom: 8px;">
              <tr>
                <td style="padding: 10px 14px;">
                  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                    <tr>
                      <td class="stack-mobile" align="left" valign="middle">
                        <span style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 13px; font-weight: 700; color: #f1f5f9;">{fail['package']}</span>
                        <span style="display: inline-block; background-color: rgba(148, 163, 184, 0.12); color: #cbd5e1; border: 1px solid #232a3e; font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 3px; margin-left: 4px; font-family: ui-monospace, monospace;">{fail['arch']}</span>
                        <span style="display: inline-block; background-color: rgba(239, 68, 68, 0.15); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.3); font-size: 9px; font-weight: 700; padding: 1px 6px; border-radius: 3px; margin-left: 4px; text-transform: uppercase;">BUILD FAILED</span>
                      </td>
                      <td class="stack-mobile-right" align="right" valign="middle">
                        <span style="font-size: 11px; color: #94a3b8; font-family: ui-monospace, monospace;">Targets: {target_vers}</span>
                      </td>
                    </tr>
                  </table>
                  <div style="font-size: 11px; color: #fca5a5; margin-top: 4px; font-family: ui-monospace, monospace;">
                    <span style="background-color: rgba(239, 68, 68, 0.2); color: #f87171; font-weight: 700; padding: 1px 4px; border-radius: 3px; font-size: 10px;">{fail_stage}</span> {fail_summary_reason}
                  </div>
                </td>
              </tr>
            </table>
            """
            compact_failure_rows.append(compact_fail)

    # Build Success Cards & Compact Rows
    success_cards_html = []
    compact_success_rows = []
    for app in success_records:
        patch_info = app["patch_info"]
        has_unapplied = len(patch_info.get("unapplied_patches", [])) > 0
        has_failed = len(patch_info.get("failed_patches", [])) > 0

        # Status badge in header
        if has_failed:
            badge_bg_hdr, badge_col_hdr = "rgba(239, 68, 68, 0.15)", "#fca5a5"
            badge_border_hdr = "rgba(239, 68, 68, 0.35)"
            badge_label_hdr = f"{len(patch_info['failed_patches'])} FAILED"
        elif has_unapplied:
            badge_bg_hdr, badge_col_hdr = "rgba(245, 158, 11, 0.15)", "#fbbf24"
            badge_border_hdr = "rgba(245, 158, 11, 0.35)"
            badge_label_hdr = f"{len(patch_info['applied_patches'])} APPLIED &bull; {len(patch_info['unapplied_patches'])} NOT APPLIED"
        else:
            badge_bg_hdr, badge_col_hdr = "rgba(16, 185, 129, 0.15)", "#6ee7b7"
            badge_border_hdr = "rgba(16, 185, 129, 0.35)"
            badge_label_hdr = f"ALL {len(patch_info['applied_patches'])} PATCHES APPLIED"

        # Checksum HTML
        checksum_html = ""
        if app["checksum"]:
            checksum_html = f"""
            <tr>
              <td colspan="2" style="padding-top: 4px; font-size: 11px; color: #64748b; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; word-break: break-all;">
                SHA-256: {app['checksum']}
              </td>
            </tr>
            """

        # Repositories Section HTML (Scanned vs Applied)
        applied_repo_badges = " ".join(
            f'<span style="display: inline-block; background-color: rgba(56, 189, 248, 0.15); color: #7dd3fc; border: 1px solid rgba(56, 189, 248, 0.35); border-radius: 4px; padding: 2px 8px; margin: 2px 4px 2px 0; font-size: 11px; font-weight: 600; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace;">{html.escape(r)}</span>'
            for r in app["applied_repos"]
        ) if app["applied_repos"] else '<span style="color: #64748b; font-size: 11px;">Default Bundle</span>'

        scanned_repo_badges = " ".join(
            f'<span style="display: inline-block; background-color: #191b22; color: #94a3b8; border: 1px solid #232a3e; border-radius: 4px; padding: 2px 8px; margin: 2px 4px 2px 0; font-size: 11px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace;">{html.escape(r)}</span>'
            for r in app["scanned_repos"]
        ) if app["scanned_repos"] else '<span style="color: #64748b; font-size: 11px;">Default</span>'

        repos_box_html = f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #0c0e14; border: 1px solid #1f2330; border-radius: 8px; margin-top: 12px;">
          <tr>
            <td style="padding: 10px 14px;">
              <div style="font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">
                Repository Sources
              </div>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td width="90" valign="top" style="padding: 2px 0; font-size: 11px; font-weight: 600; color: #64748b; text-transform: uppercase;">
                    Applied ({len(app['applied_repos'])}):
                  </td>
                  <td valign="top" style="padding: 2px 0; line-height: 22px;">
                    {applied_repo_badges}
                  </td>
                </tr>
                <tr>
                  <td width="90" valign="top" style="padding: 4px 0 2px 0; font-size: 11px; font-weight: 600; color: #64748b; text-transform: uppercase;">
                    Scanned ({len(app['scanned_repos'])}):
                  </td>
                  <td valign="top" style="padding: 4px 0 2px 0; line-height: 22px;">
                    {scanned_repo_badges}
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
        """

        # Fallback progression notice (clearly distinguished from failures)
        fallback_notice_html = ""
        if app["attempts"]:
            prog_items = "".join(
                f'<div style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; color: #cbd5e1; margin-top: 4px;">'
                f'<span style="color: #38bdf8; font-weight: 700;">&bull; Target v{str(att.get("version")[0]) if isinstance(att.get("version"), (tuple, list)) and len(att.get("version")) > 0 else (att.get("version") or att.get("target_version") or "target")}:</span> '
                f'{format_strategy_name(att.get("run", 1), short=True)} ({att.get("stage", "patch")}) &mdash; {att.get("reason", "incompatible")}</div>'
                for att in app["attempts"]
            )
            fallback_notice_html = f"""
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #0c0e14; border: 1px solid #192734; border-left: 3px solid #38bdf8; border-radius: 6px; margin-top: 12px;">
              <tr>
                <td style="padding: 10px 14px;">
                  <div style="font-size: 11px; font-weight: 700; color: #38bdf8; text-transform: uppercase; letter-spacing: 0.5px;">
                    &#8505; Fallback Version Progression
                  </div>
                  <div style="font-size: 12px; color: #94a3b8; margin-top: 2px;">
                    Successfully settled on <strong style="color: #f8fafc;">v{app['version']}</strong> via <strong style="color: #38bdf8;">{app['winning_badge']}</strong> after prior attempts:
                  </div>
                  {prog_items}
                </td>
              </tr>
            </table>
            """

        # Applied patches chips (Email-safe inline-block wrapping with compact markup)
        applied_list = patch_info.get("applied_patches", [])
        if applied_list:
            # If large number of patches (e.g. YouTube with 80+), cap detailed chips to prevent Gmail 102KB clipping
            max_chips = 15
            displayed_patches = applied_list[:max_chips]
            overflow_count = len(applied_list) - max_chips

            chips_html_list = [
                f'<span style="display: inline-block; background-color: #162026; border: 1px solid #23373e; border-radius: 8px; padding: 2px 7px; margin: 2px 3px 2px 0; font-size: 11px; line-height: 16px; color: #cbd5e1; white-space: normal;">'
                f'<span style="color: #34d399; font-weight: bold; margin-right: 3px;">&bull;</span>{html.escape(p)}</span>'
                for p in displayed_patches
            ]
            if overflow_count > 0:
                chips_html_list.append(
                    f'<span style="display: inline-block; background-color: rgba(56, 189, 248, 0.12); border: 1px solid rgba(56, 189, 248, 0.35); border-radius: 8px; padding: 2px 7px; margin: 2px 3px 2px 0; font-size: 11px; line-height: 16px; color: #38bdf8; font-weight: 600;">'
                    f'+{overflow_count} more patches applied</span>'
                )
            applied_chips = " ".join(chips_html_list)
            applied_box_html = f"""
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #0c0e14; border: 1px solid #1e262c; border-radius: 8px; margin-top: 10px;">
              <tr>
                <td style="padding: 10px 12px;">
                  <div style="font-size: 11px; font-weight: 700; color: #34d399; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">
                    &#10004; Applied Patches ({len(applied_list)})
                  </div>
                  <div style="line-height: 20px;">
                    {applied_chips}
                  </div>
                </td>
              </tr>
            </table>
            """
        else:
            applied_box_html = ""

        # Alias Resolution Box (Informational)
        superseded_items = "".join(
            f"""
            <div style="font-size: 11px; color: #cbd5e1; margin-top: 3px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;">
              <span style="color: #38bdf8; font-weight: bold; margin-right: 4px;">&bull;</span>
              <strong>{html.escape(str(sp['name']))}</strong>
              <span style="color: #64748b;">(satisfied by <strong style="color: #34d399;">'{html.escape(str(sp['applied_as']))}'</strong>)</span>
            </div>
            """
            for sp in patch_info.get("superseded_patches", [])
        )
        superseded_box_html = f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #0c0e14; border: 1px solid #192734; border-left: 3px solid #38bdf8; border-radius: 8px; margin-top: 10px;">
          <tr>
            <td style="padding: 10px 12px;">
              <div style="font-size: 11px; font-weight: 700; color: #38bdf8; text-transform: uppercase; letter-spacing: 0.5px;">
                &#8505; Alias Resolution ({len(patch_info.get('superseded_patches', []))})
              </div>
              <div style="margin-top: 4px;">
                {superseded_items}
              </div>
            </td>
          </tr>
        </table>
        """ if patch_info.get("superseded_patches") else ""

        # Not applied patches chips (Email-safe inline-block wrapping)
        unapplied_chips_list = []
        for p in patch_info.get("unapplied_patches", []):
            reason_html = f" <span style=\"color: #94a3b8;\">({html.escape(str(p['reason']))})</span>" if p.get("reason") else ""
            unapplied_chips_list.append(
                f'<span style="display: inline-block; background-color: #1e1d24; border: 1px solid #3d3326; border-radius: 8px; padding: 2px 7px; margin: 2px 3px 2px 0; font-size: 11px; line-height: 16px; color: #e2e8f0; white-space: normal;">'
                f'<span style="color: #fbbf24; font-weight: bold; margin-right: 3px;">&bull;</span>{html.escape(str(p["name"]))}{reason_html}</span>'
            )
        unapplied_chips = " ".join(unapplied_chips_list)
        unapplied_box_html = f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #0c0e14; border: 1px solid #2d261e; border-left: 3px solid #f59e0b; border-radius: 8px; margin-top: 10px;">
          <tr>
            <td style="padding: 10px 12px;">
              <div style="font-size: 11px; font-weight: 700; color: #fbbf24; text-transform: uppercase; letter-spacing: 0.5px;">
                Not Applied ({len(patch_info.get('unapplied_patches', []))})
              </div>
              <div style="line-height: 20px;">
                {unapplied_chips}
              </div>
            </td>
          </tr>
        </table>
        """ if patch_info.get("unapplied_patches") else ""

        # Explicitly failed patches box
        failed_items = "".join(
            f"""
            <div style="font-size: 11px; color: #fca5a5; margin-top: 3px;">
              <strong>{html.escape(str(fp['name']))}</strong>: {html.escape(str(fp['reason']))}
            </div>
            """
            for fp in patch_info.get("failed_patches", [])
        )
        failed_box_html = f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #0c0e14; border: 1px solid #331f24; border-left: 3px solid #ef4444; border-radius: 8px; margin-top: 10px;">
          <tr>
            <td style="padding: 10px 12px;">
              <div style="font-size: 11px; font-weight: 700; color: #f87171; text-transform: uppercase; letter-spacing: 0.5px;">
                Explicitly Failed Patches ({len(patch_info.get('failed_patches', []))})
              </div>
              {failed_items}
            </td>
          </tr>
        </table>
        """ if patch_info.get("failed_patches") else ""

        # Download CTA Button(s) (Email-Safe Bulletproof Button with high-contrast text)
        if app.get("download_urls") and len(app["download_urls"]) > 1:
            btn_cells = []
            width_pct = int(100 / len(app["download_urls"]))
            for ep_id, ep_info in app["download_urls"].items():
                bg_col = ep_info.get("color", "#0284c7")
                btn_cells.append(f"""
                <td class="stack-mobile" align="center" style="width: {width_pct}%; padding: 4px 6px;">
                  <a href="{ep_info['url']}" target="_blank" style="display: block; box-sizing: border-box; background-color: {bg_col}; color: #ffffff !important; text-decoration: none; font-size: 12px; font-weight: 700; text-align: center; padding: 10px 12px; border-radius: 8px; line-height: 1.3;">
                    <span style="color: #ffffff !important;">{ep_info.get('icon', '')} {ep_info['label']}</span>
                    <span style="display: inline-block; background-color: rgba(0, 0, 0, 0.25); color: #ffffff !important; padding: 2px 6px; border-radius: 4px; margin-left: 4px; font-size: 11px;">{app['file_size']}</span>
                  </a>
                </td>
                """)
            download_btn_html = f"""
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top: 14px;">
              <tr>
                {''.join(btn_cells)}
              </tr>
            </table>
            """
        elif app.get("download_urls") and len(app["download_urls"]) == 1:
            ep_info = next(iter(app["download_urls"].values()))
            bg_col = ep_info.get("color", "#0284c7")
            download_btn_html = f"""
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top: 14px;">
              <tr>
                <td align="center">
                  <a href="{ep_info['url']}" target="_blank" style="display: inline-block; width: 100%; max-width: 440px; box-sizing: border-box; background-color: {bg_col}; color: #ffffff !important; text-decoration: none; font-size: 13px; font-weight: 700; text-align: center; padding: 11px 16px; border-radius: 8px; line-height: 1.3;">
                    <span style="color: #ffffff !important;">{ep_info.get('icon', '⚡')} Download Patched APK ({ep_info['label']})</span>
                    <span style="display: inline-block; background-color: rgba(0, 0, 0, 0.25); color: #ffffff !important; padding: 2px 7px; border-radius: 4px; margin-left: 6px; font-size: 11px; font-weight: 600;">{app['file_size']}</span>
                  </a>
                </td>
              </tr>
            </table>
            """
        elif app.get("download_url"):
            download_btn_html = f"""
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top: 14px;">
              <tr>
                <td align="center">
                  <a href="{app['download_url']}" target="_blank" style="display: inline-block; width: 100%; max-width: 440px; box-sizing: border-box; background-color: #0284c7; color: #ffffff !important; text-decoration: none; font-size: 13px; font-weight: 700; text-align: center; padding: 11px 16px; border-radius: 8px; line-height: 1.3;">
                    <span style="color: #ffffff !important;">&#11015; Download Patched APK</span>
                    <span style="display: inline-block; background-color: rgba(0, 0, 0, 0.25); color: #ffffff !important; padding: 2px 7px; border-radius: 4px; margin-left: 6px; font-size: 11px; font-weight: 600;">{app['file_size']}</span>
                  </a>
                </td>
              </tr>
            </table>
            """
        else:
            download_btn_html = """
            <div style="margin-top: 10px; font-size: 11px; color: #94a3b8; font-style: italic; text-align: center;">
              Download link unavailable (file outside serve root)
            </div>
            """

        # Step summary footer
        step_passed_count = sum(1 for s in patch_info.get("steps", []) if s.get("success"))
        total_steps_count = len(patch_info.get("steps", []))
        step_badge_text = f"{step_passed_count}/{total_steps_count} steps passed" if total_steps_count > 0 else "verified"

        success_card = f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #141720; border: 1px solid #1f2d2b; border-radius: 12px; overflow: hidden; border-top: 2px solid #10b981; margin-bottom: 16px;">
          <tr>
            <td style="padding: 16px 18px;">
              <!-- Package Title Bar with Permanently Visible ARCH tag & Winning Strategy/Attempt Badge -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td class="stack-mobile" align="left" valign="middle">
                    <span style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 15px; font-weight: 700; color: #f8fafc;">{app['package']}</span>
                    <span style="display: inline-block; background-color: rgba(56, 189, 248, 0.15); color: #7dd3fc; border: 1px solid rgba(56, 189, 248, 0.3); font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 4px; margin-left: 6px;">v{app['version']}</span>
                    <!-- Persistent Architecture Tag -->
                    <span style="display: inline-block; background-color: rgba(148, 163, 184, 0.12); color: #cbd5e1; border: 1px solid #232a3e; font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 4px; margin-left: 6px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace;">{app['arch']}</span>
                    <!-- Winning Strategy & Attempt Pill -->
                    <span style="display: inline-block; background-color: rgba(56, 189, 248, 0.12); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 4px; margin-left: 6px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace;">{app['winning_badge']}</span>
                  </td>
                  <td class="stack-mobile-right" align="right" valign="middle">
                    <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="background-color: {badge_bg_hdr}; border: 1px solid {badge_border_hdr}; border-radius: 6px;">
                      <tr>
                        <td style="padding: 3px 8px; text-align: center;">
                          <div style="font-size: 10px; font-weight: 800; color: {badge_col_hdr}; text-transform: uppercase; letter-spacing: 0.3px;">{badge_label_hdr}</div>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- File & Build Resolution Info -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top: 10px;">
                <tr>
                  <td align="left" style="font-size: 12px; color: #94a3b8;">
                    Output APK: <code style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; color: #e2e8f0; background-color: #0c0e14; padding: 2px 7px; border-radius: 4px; border: 1px solid #1f2330;">{app['filename']}</code>
                  </td>
                  <td align="right" style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; color: #94a3b8; font-weight: 600;">
                    {app['file_size']}
                  </td>
                </tr>
                <tr>
                  <td colspan="2" style="padding-top: 4px; font-size: 11px; color: #94a3b8;">
                    Build Resolution: <strong style="color: #7dd3fc; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace;">{app['winning_full']}</strong>
                  </td>
                </tr>
                {checksum_html}
              </table>

              {repos_box_html}
              {fallback_notice_html}
              {applied_box_html}
              {superseded_box_html}
              {unapplied_box_html}
              {failed_box_html}
              {download_btn_html}

              <!-- Pipeline Step Summary Footer Bar -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #0c0e14; border: 1px solid #1f2330; border-radius: 6px; margin-top: 12px;">
                <tr>
                  <td style="padding: 7px 12px;" align="left">
                    <span style="font-size: 11px; color: #94a3b8; font-weight: 600;">
                      &#10003; Verification Pipeline
                    </span>
                  </td>
                  <td style="padding: 7px 12px;" align="right">
                    <span style="font-size: 11px; font-weight: 700; color: #34d399; background-color: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.3); padding: 2px 6px; border-radius: 4px;">{step_badge_text}</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
        """
        success_cards_html.append(success_card)

        # Compact success row
        if has_failed:
            row_border = "#ef4444"
            status_chip = f'<span style="display: inline-block; background-color: rgba(239, 68, 68, 0.15); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.3); font-size: 9px; font-weight: 700; padding: 1px 6px; border-radius: 3px; text-transform: uppercase;">{len(patch_info["failed_patches"])} FAILED</span>'
        elif has_unapplied:
            row_border = "#f59e0b"
            status_chip = f'<span style="display: inline-block; background-color: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); font-size: 9px; font-weight: 700; padding: 1px 6px; border-radius: 3px; text-transform: uppercase;">{len(patch_info["applied_patches"])} OK &bull; {len(patch_info["unapplied_patches"])} SKIPPED</span>'
        else:
            row_border = "#10b981"
            status_chip = f'<span style="display: inline-block; background-color: rgba(16, 185, 129, 0.15); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.3); font-size: 9px; font-weight: 700; padding: 1px 6px; border-radius: 3px; text-transform: uppercase;">{len(patch_info["applied_patches"])} PATCHES</span>'

        if app.get("download_urls") and len(app["download_urls"]) > 1:
            btn_items = []
            for ep_id, ep_info in app["download_urls"].items():
                bg_col = ep_info.get("color", "#0284c7")
                badge_lbl = ep_info.get("badge", ep_info["label"])
                btn_items.append(
                    f'<a href="{ep_info["url"]}" target="_blank" style="display: inline-block; background-color: {bg_col}; color: #ffffff !important; font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 4px; text-decoration: none; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; white-space: nowrap; margin-left: 4px;">{ep_info.get("icon", "")} {badge_lbl}</a>'
                )
            compact_dl_btn = "".join(btn_items)
        elif app.get("download_urls") and len(app["download_urls"]) == 1:
            ep_info = next(iter(app["download_urls"].values()))
            bg_col = ep_info.get("color", "#38bdf8")
            compact_dl_btn = f'<a href="{ep_info["url"]}" target="_blank" style="display: inline-block; background-color: {bg_col}; color: #ffffff !important; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 4px; text-decoration: none; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; white-space: nowrap;">⚡ Download</a>'
        elif app.get("download_url"):
            compact_dl_btn = f'<a href="{app["download_url"]}" target="_blank" style="display: inline-block; background-color: #38bdf8; color: #0c0e14; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 4px; text-decoration: none; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; white-space: nowrap;">⚡ Download</a>'
        else:
            compact_dl_btn = '<span style="display: inline-block; background-color: #191b22; color: #64748b; border: 1px solid #232a3e; font-size: 10px; font-weight: 600; padding: 3px 8px; border-radius: 4px; font-family: ui-monospace, monospace;">Local Only</span>'

        details_lines = []
        if has_failed:
            failed_names = ", ".join(html.escape(p["name"]) for p in patch_info["failed_patches"])
            details_lines.append(f'<div style="font-size: 11px; color: #fca5a5; margin-top: 4px; font-family: ui-monospace, monospace;"><span style="background-color: rgba(239, 68, 68, 0.2); color: #f87171; font-weight: 700; padding: 1px 4px; border-radius: 3px; font-size: 10px;">FAILED</span> {failed_names}</div>')
        if has_unapplied:
            unapp_list = patch_info["unapplied_patches"]
            unapp_sample = ", ".join(html.escape(p["name"]) for p in unapp_list[:4])
            overflow = f" (+{len(unapp_list) - 4} more)" if len(unapp_list) > 4 else ""
            details_lines.append(f'<div style="font-size: 11px; color: #fbbf24; margin-top: 4px; font-family: ui-monospace, monospace;"><span style="background-color: rgba(245, 158, 11, 0.2); color: #fbbf24; font-weight: 700; padding: 1px 4px; border-radius: 3px; font-size: 10px;">NOT APPLIED</span> {unapp_sample}{overflow}</div>')

        if not details_lines and app.get("winning_badge"):
            details_lines.append(f'<div style="font-size: 11px; color: #64748b; margin-top: 4px; font-family: ui-monospace, monospace;">Resolved: {html.escape(str(app["winning_badge"]))}</div>')

        compact_details_html = "".join(details_lines)

        compact_success_row = f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #141720; border: 1px solid #1f2533; border-left: 3px solid {row_border}; border-radius: 8px; margin-bottom: 8px;">
          <tr>
            <td style="padding: 10px 14px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td class="stack-mobile" align="left" valign="middle">
                    <span style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 13px; font-weight: 700; color: #f1f5f9;">{app['package']}</span>
                    <span style="display: inline-block; background-color: rgba(56, 189, 248, 0.12); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 3px; margin-left: 4px; font-family: ui-monospace, monospace;">v{app['version']}</span>
                    <span style="display: inline-block; background-color: rgba(148, 163, 184, 0.12); color: #cbd5e1; border: 1px solid #232a3e; font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 3px; margin-left: 4px; font-family: ui-monospace, monospace;">{app['arch']}</span>
                    <span style="font-size: 11px; color: #64748b; margin-left: 4px; font-family: ui-monospace, monospace;">{app['file_size']}</span>
                    <span style="margin-left: 4px;">{status_chip}</span>
                  </td>
                  <td class="stack-mobile-right" align="right" valign="middle" style="padding-left: 8px;">
                    {compact_dl_btn}
                  </td>
                </tr>
              </table>
              {compact_details_html}
            </td>
          </tr>
        </table>
        """
        compact_success_rows.append(compact_success_row)

    # General Flags & Build Parameters Bar HTML
    striplibs_chip = (
        f'<span style="display: inline-block; background-color: rgba(56, 189, 248, 0.12); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: 600; font-family: ui-monospace, monospace; margin: 2px 3px;">--striplibs: <strong>{global_arch}</strong></span>'
        if striplibs_val
        else '<span style="display: inline-block; background-color: #191b22; color: #64748b; border: 1px solid #232a3e; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-family: ui-monospace, monospace; margin: 2px 3px;">--striplibs: off</span>'
    )
    low_spec_chip = (
        '<span style="display: inline-block; background-color: rgba(245, 158, 11, 0.12); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: 600; font-family: ui-monospace, monospace; margin: 2px 3px;">low-spec: active</span>'
        if low_spec_val
        else '<span style="display: inline-block; background-color: #191b22; color: #64748b; border: 1px solid #232a3e; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-family: ui-monospace, monospace; margin: 2px 3px;">low-spec: off</span>'
    )
    arch_chip = f'<span style="display: inline-block; background-color: #191b22; color: #cbd5e1; border: 1px solid #232a3e; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-family: ui-monospace, monospace; margin: 2px 3px;">arch: <strong>{global_arch}</strong></span>'


    general_flags_section_html = f"""
    <tr>
      <td style="padding: 14px 28px 4px 28px;" class="content-padding">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #12151e; border: 1px solid #1f2533; border-radius: 8px;">
          <tr>
            <td style="padding: 10px 14px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td class="stack-mobile" align="left" valign="middle">
                    <span style="font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px;">
                      ⚙️ Build Parameters &amp; Flags
                    </span>
                  </td>
                  <td class="stack-mobile-right" align="right" valign="middle">
                    {striplibs_chip}
                    {arch_chip}
                    {low_spec_chip}
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>
    """

    # Execution Log Drawer (supplementary)
    log_section_html = ""
    if raw_log_str:
        log_section_html = f"""
        <tr>
          <td style="padding: 0 28px 16px 28px;" class="content-padding">
            <details style="border: 1px solid #1f2330; border-radius: 8px; background-color: #141720; overflow: hidden;">
              <summary style="padding: 10px 14px; font-size: 12px; font-weight: 600; color: #38bdf8; cursor: pointer; user-select: none;">
                &#9654; Program Execution Log
              </summary>
              <pre style="margin: 0; padding: 14px; font-size: 11px; color: #cbd5e1; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; overflow-x: auto; max-height: 320px; white-space: pre-wrap;">{raw_log_str}</pre>
            </details>
          </td>
        </tr>
        """

    # Section Assemblies for Full Detailed Cards
    full_failures_sec = ""
    if failure_cards_html:
        full_failures_sec = f"""
        <tr>
          <td style="padding: 20px 28px 4px 28px;" class="content-padding">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 10px;">
              <tr>
                <td align="left">
                  <span style="font-size: 12px; font-weight: 800; color: #f87171; letter-spacing: 0.8px; text-transform: uppercase;">
                    &#10006; Pipeline Failure
                  </span>
                </td>
                <td align="right">
                  <span style="font-size: 11px; color: #94a3b8; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;">{total_failures} app{'s' if total_failures != 1 else ''} failed</span>
                </td>
              </tr>
            </table>
            {''.join(failure_cards_html)}
          </td>
        </tr>
        """

    full_success_sec = ""
    if success_cards_html:
        full_success_sec = f"""
        <tr>
          <td style="padding: 16px 28px 20px 28px;" class="content-padding">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 10px;">
              <tr>
                <td align="left">
                  <span style="font-size: 12px; font-weight: 800; color: #34d399; letter-spacing: 0.8px; text-transform: uppercase;">
                    &#10004; Ready for Download
                  </span>
                </td>
                <td align="right">
                  <span style="font-size: 11px; color: #94a3b8; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;">signed &amp; verified</span>
                </td>
              </tr>
            </table>
            {''.join(success_cards_html)}
          </td>
        </tr>
        """

    # Section Assemblies for Compact Overview Table
    compact_failures_sec = ""
    if compact_failure_rows:
        compact_failures_sec = f"""
        <tr>
          <td style="padding: 20px 28px 4px 28px;" class="content-padding">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 10px;">
              <tr>
                <td align="left">
                  <span style="font-size: 12px; font-weight: 800; color: #f87171; letter-spacing: 0.8px; text-transform: uppercase;">
                    &#10006; Pipeline Failures ({total_failures})
                  </span>
                </td>
                <td align="right">
                  <span style="font-size: 11px; color: #94a3b8; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;">compact overview</span>
                </td>
              </tr>
            </table>
            {''.join(compact_failure_rows)}
          </td>
        </tr>
        """

    compact_success_sec = ""
    if compact_success_rows:
        compact_success_sec = f"""
        <tr>
          <td style="padding: 16px 28px 20px 28px;" class="content-padding">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 10px;">
              <tr>
                <td align="left">
                  <span style="font-size: 12px; font-weight: 800; color: #34d399; letter-spacing: 0.8px; text-transform: uppercase;">
                    &#10004; Ready for Download ({total_success})
                  </span>
                </td>
                <td align="right">
                  <span style="font-size: 11px; color: #94a3b8; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;">compact overview</span>
                </td>
              </tr>
            </table>
            {''.join(compact_success_rows)}
          </td>
        </tr>
        """

    # 1. Always generate the Full Detailed Cards document (for Web Report & low-volume emails)
    full_cards_doc = assemble_html_document(
        subject=subject,
        badge_bg=badge_bg,
        badge_border=badge_border,
        badge_dot=badge_dot,
        badge_color=badge_color,
        badge_text=badge_text,
        now_str=now_str,
        host_display=host_display,
        total_success=total_success,
        total_failures=total_failures,
        succeeded_chips_html=succeeded_chips_html,
        failed_chips_html=failed_chips_html,
        duration_str=duration_str,
        general_flags_section_html=general_flags_section_html,
        failures_section_html=full_failures_sec,
        success_section_html=full_success_sec,
        log_section_html=log_section_html,
        banner_html="",
        bottom_banner_html="",
        web_report_url=web_report_url,
        web_report_endpoints=web_report_endpoints,
        security_badge_text=security_badge_text,
    )

    # 2. Save full cards document to reports directory in state
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text(full_cards_doc, encoding="utf-8")
        logger.info(f"Saved full build report to: {report_path}")

        # Clean up legacy build_report.html in patched_dir if present
        legacy_report_path = patched_dir / report_filename
        if legacy_report_path.is_file():
            try:
                legacy_report_path.unlink()
                logger.info(f"Cleaned up legacy report file from: {legacy_report_path}")
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Failed to write full build report to {report_path}: {e}")

    # 3. Determine Layout Mode for Email
    layout_mode = str(email_conf.get("layout_mode", "auto")).lower()
    compact_threshold = int(email_conf.get("compact_threshold", 15))
    total_apps = total_success + total_failures

    is_compact = (layout_mode == "compact") or (layout_mode == "auto" and total_apps > compact_threshold)

    # 4. Assemble Email HTML
    if is_compact:
        top_banner_html = ""
        bottom_banner_html = ""
        if web_report_endpoints and len(web_report_endpoints) > 1:
            top_links_html = "".join([
                f'<a href="{ep["url"]}" target="_blank" style="display: inline-block; background-color: {ep.get("color", "#0284c7")}; color: #ffffff !important; font-size: 11px; font-weight: 700; padding: 6px 12px; border-radius: 6px; text-decoration: none; white-space: nowrap; margin-left: 6px;">{ep.get("icon", "")} {ep.get("label", "Report")} Cards &rarr;</a>'
                for ep in web_report_endpoints if ep.get("url")
            ])
            top_banner_html = f"""
            <tr>
              <td style="padding: 14px 28px 4px 28px;" class="content-padding">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #121927; border: 1px solid #1e3a5f; border-left: 3px solid #38bdf8; border-radius: 8px;">
                  <tr>
                    <td style="padding: 12px 16px;">
                      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                        <tr>
                          <td class="stack-mobile" align="left" valign="middle">
                            <div style="font-size: 12px; font-weight: 700; color: #38bdf8;">
                              ⚡ Compact View Active ({total_apps} apps)
                            </div>
                            <div style="font-size: 11px; color: #94a3b8; margin-top: 2px;">
                              Condensed overview to prevent email clipping. Full reports available via mirrors:
                            </div>
                          </td>
                          <td class="stack-mobile-right" align="right" valign="middle" style="padding-left: 12px;">
                            {top_links_html}
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            """

            bottom_links_html = "".join([
                f'<a href="{ep["url"]}" target="_blank" style="display: inline-block; background-color: {ep.get("color", "#0284c7")}; color: #ffffff !important; font-size: 12px; font-weight: 700; padding: 8px 18px; border-radius: 6px; text-decoration: none; margin: 4px;">{ep.get("icon", "")} {ep.get("label", "Mirror")} Detailed Report &rarr;</a>'
                for ep in web_report_endpoints if ep.get("url")
            ])
            bottom_banner_html = f"""
            <tr>
              <td style="padding: 10px 28px 20px 28px; text-align: center;" class="content-padding">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #121927; border: 1px solid #1e3a5f; border-radius: 8px;">
                  <tr>
                    <td style="padding: 16px; text-align: center;">
                      <div style="font-size: 13px; font-weight: 700; color: #f1f5f9; margin-bottom: 6px;">
                        Need complete details, patch logs, or unapplied reasons?
                      </div>
                      <div style="font-size: 12px; color: #94a3b8; margin-bottom: 12px;">
                        The full-fidelity report with all cards, checksums, and repository metadata is hosted online across active mirrors.
                      </div>
                      <div>
                        {bottom_links_html}
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            """
        elif web_report_url:
            top_banner_html = f"""
            <tr>
              <td style="padding: 14px 28px 4px 28px;" class="content-padding">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #121927; border: 1px solid #1e3a5f; border-left: 3px solid #38bdf8; border-radius: 8px;">
                  <tr>
                    <td style="padding: 12px 16px;">
                      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                        <tr>
                          <td class="stack-mobile" align="left" valign="middle">
                            <div style="font-size: 12px; font-weight: 700; color: #38bdf8;">
                              ⚡ Compact View Active ({total_apps} apps)
                            </div>
                            <div style="font-size: 11px; color: #94a3b8; margin-top: 2px;">
                              Condensed overview to prevent email clipping.
                            </div>
                          </td>
                          <td class="stack-mobile-right" align="right" valign="middle" style="padding-left: 12px;">
                            <a href="{web_report_url}" target="_blank" style="display: inline-block; background-color: #38bdf8; color: #0c0e14; font-size: 11px; font-weight: 700; padding: 6px 14px; border-radius: 6px; text-decoration: none; white-space: nowrap;">🌐 View Full Cards &rarr;</a>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            """

            bottom_banner_html = f"""
            <tr>
              <td style="padding: 10px 28px 20px 28px; text-align: center;" class="content-padding">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #121927; border: 1px solid #1e3a5f; border-radius: 8px;">
                  <tr>
                    <td style="padding: 16px; text-align: center;">
                      <div style="font-size: 13px; font-weight: 700; color: #f1f5f9; margin-bottom: 6px;">
                        Need complete details, patch logs, or unapplied reasons?
                      </div>
                      <div style="font-size: 12px; color: #94a3b8; margin-bottom: 12px;">
                        The full-fidelity report with all cards, checksums, and repository metadata is hosted online.
                      </div>
                      <div>
                        <a href="{web_report_url}" target="_blank" style="display: inline-block; background-color: #38bdf8; color: #0c0e14; font-size: 12px; font-weight: 700; padding: 8px 20px; border-radius: 6px; text-decoration: none;">🌐 Open Full Detailed Cards Report &rarr;</a>
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            """
        else:
            top_banner_html = f"""
            <tr>
              <td style="padding: 14px 28px 4px 28px;" class="content-padding">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #121927; border: 1px solid #1e3a5f; border-left: 3px solid #38bdf8; border-radius: 8px;">
                  <tr>
                    <td style="padding: 10px 14px;">
                      <div style="font-size: 12px; font-weight: 700; color: #38bdf8;">
                        ⚡ Compact View Active ({total_apps} apps)
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            """

        html_body = assemble_html_document(
            subject=subject,
            badge_bg=badge_bg,
            badge_border=badge_border,
            badge_dot=badge_dot,
            badge_color=badge_color,
            badge_text=badge_text,
            now_str=now_str,
            host_display=host_display,
            total_success=total_success,
            total_failures=total_failures,
            succeeded_chips_html=succeeded_chips_html,
            failed_chips_html=failed_chips_html,
            duration_str=duration_str,
            general_flags_section_html=general_flags_section_html,
            failures_section_html=compact_failures_sec,
            success_section_html=compact_success_sec,
            log_section_html=log_section_html,
            banner_html=top_banner_html,
            bottom_banner_html=bottom_banner_html,
            web_report_url=web_report_url,
            web_report_endpoints=web_report_endpoints,
            security_badge_text=security_badge_text,
        )
    else:
        html_body = full_cards_doc

    return subject, text_body, html_body, attachments


# ---------------------------------------------------------------------------
# SMTP Transmission
# ---------------------------------------------------------------------------

def send_email(
    subject: str,
    text_body: str,
    html_body: str,
    config: dict,
    attachments: list[Path] | None = None,
) -> None:
    """
    Sends dual-MIME email using configured SMTP server and environment credentials.
    Performs strictly SMTP transmission (no dry-run branching).
    """
    email_conf = config["email"]
    smtp_server = email_conf["smtp_server"]
    smtp_port = email_conf["smtp_port"]
    use_tls = email_conf["use_tls"]
    use_ssl = email_conf["use_ssl"]
    sender_name = email_conf["sender_name"]
    sender_email = email_conf["sender_email"]
    recipients = email_conf["recipients"]
    username = email_conf.get("username", "")
    password = email_conf.get("password", "")

    if not recipients:
        raise ValueError("Cannot send email: No recipients specified in config.yaml")

    # Construct Root MIME message
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = f"{sender_name} <{sender_email}>"
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=smtp_server if "." in smtp_server else "patcher.local")

    # Alternative container for Plain Text + HTML
    msg_alt = MIMEMultipart("alternative")
    msg_alt.attach(MIMEText(text_body, "plain", "utf-8"))
    msg_alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(msg_alt)

    # Attachments
    if attachments:
        for file_path in attachments:
            if not file_path.is_file():
                continue
            try:
                part = MIMEApplication(file_path.read_bytes(), Name=file_path.name)
                part["Content-Disposition"] = f'attachment; filename="{file_path.name}"'
                msg.attach(part)
            except Exception as e:
                logger.warning(f"Failed to attach '{file_path}': {e}")

    # Connect and transmit
    logger.info(f"Connecting to SMTP server {smtp_server}:{smtp_port}...")
    if use_ssl:
        server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30)
    else:
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)

    try:
        if use_tls and not use_ssl:
            server.starttls()

        if username and password:
            logger.info(f"Authenticating as '{username}'...")
            server.login(username, password)

        server.send_message(msg, from_addr=sender_email, to_addrs=recipients)
        logger.info(f" └── [✓] Email successfully sent to {', '.join(recipients)}")
    finally:
        try:
            server.quit()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main Orchestration & CLI
# ---------------------------------------------------------------------------

def main(
    patch_success: dict[str, Path | dict],
    failures: dict[str, dict] | None = None,
    log_content: str | Path | None = None,
    duration: str | float | int | None = None,
    dry_run: bool = False,
    project_root: Path | None = None,
    build_flags: dict | None = None,
) -> tuple[Path | None, str]:
    """
    Main dispatch entrypoint.
    - patch_success: {pkg: Path} or {pkg: {"dest": Path, "arch": "...", "scanned_repos": [...], "applied_repos": [...], "strategy": 1, "attempt": 1, "attempts": [...]}}
    - failures: {pkg: {"target_versions": [...], "arch": "...", "scanned_repos": [...], "applied_repos": [...], "attempts": [...]}}
    - duration: elapsed time string (e.g. "3m 14s") or seconds float/int (or None for N/A)
    - build_flags: optional dict containing global flags e.g. {"striplibs": True, "architecture": "arm64-v8a", "low_spec_mode": False}
    - If dry_run is True: writes test_email.html, prints plain-text to console,
      and makes zero SMTP or network calls.
    - Else: calls send_email().
    """
    failures = failures or {}
    for f_data in failures.values():
        if isinstance(f_data, dict) and "target_versions" in f_data:
            raw_t = f_data["target_versions"]
            if raw_t:
                f_data["target_versions"] = [
                    str(t[0]) if isinstance(t, (tuple, list)) and len(t) > 0 else str(t)
                    for t in (list(raw_t) if isinstance(raw_t, (list, tuple, set)) else [raw_t])
                    if t is not None
                ]

    if not patch_success and not failures:
        logger.info("No successful patches or pipeline failures to dispatch. Exiting.")
        return None, ""

    config = load_config(project_root)
    project_root = config.get("project_root") or project_root or Path(__file__).resolve().parent.parent
    subject, text_body, html_body, attachments = generate_email_content(
        patch_success,
        failures,
        config,
        project_root,
        log_content=log_content,
        duration=duration,
        build_flags=build_flags,
        
    )

    # Save structured last run report for dashboard diagnostics
    try:
        root = config.get("project_root") or Path(__file__).resolve().parent.parent

        def _clean_for_json(obj: Any) -> Any:
            if isinstance(obj, Path):
                return str(obj)
            if isinstance(obj, set):
                return list(obj)
            if isinstance(obj, dict):
                return {k: _clean_for_json(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_clean_for_json(x) for x in obj]
            return obj

        serialized_success = {}
        for k, v in patch_success.items():
            if isinstance(v, dict):
                serialized_success[k] = {
                    "dest": str(v.get("dest", "")),
                    "arch": v.get("arch", ""),
                    "scanned_repos": _clean_for_json(v.get("scanned_repos", [])),
                    "applied_repos": _clean_for_json(v.get("applied_repos", [])),
                    "strategy": v.get("strategy"),
                    "attempt": v.get("attempt"),
                    "attempts": _clean_for_json(v.get("attempts", [])),
                }
            else:
                serialized_success[k] = {"dest": str(v), "attempts": []}

        report_data = {
            "timestamp": time.time(),
            "duration": duration,
            "success": serialized_success,
            "failures": _clean_for_json(failures),
        }
        raw_state_loc = config.get("state_location")
        if raw_state_loc:
            s_path = Path(raw_state_loc)
            state_dir = s_path if s_path.is_absolute() else (root / s_path).resolve()
        else:
            state_dir = (root / "tools" / "automorph-data" / "state").resolve()
            if not state_dir.exists() and (root / "tools" / "state").exists():
                state_dir = (root / "tools" / "state").resolve()

        report_file = state_dir / "logs" / "last_run_report.json"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(json.dumps(report_data, indent=2), encoding="utf-8")

        # Persist individual package run reports so cards always reflect the last run on that specific package
        pkg_runs_dir = state_dir / "package_runs"
        pkg_runs_dir.mkdir(parents=True, exist_ok=True)
        now_ts = time.time()
        for pkg_name, s_data in serialized_success.items():
            try:
                pkg_file = pkg_runs_dir / f"{pkg_name}.json"
                (pkg_runs_dir / f"{pkg_name}.json").write_text(json.dumps({
                    "package": pkg_name,
                    "status": "success",
                    "timestamp": now_ts,
                    "duration": duration,
                    **s_data
                }, indent=2), encoding="utf-8")
            except Exception:
                pass
        for pkg_name, f_data in failures.items():
            try:
                clean_f = _clean_for_json(f_data) if isinstance(f_data, dict) else {"reason": str(f_data)}
                (pkg_runs_dir / f"{pkg_name}.json").write_text(json.dumps({
                    "package": pkg_name,
                    "status": "failed",
                    "timestamp": now_ts,
                    "duration": duration,
                    **clean_f
                }, indent=2), encoding="utf-8")
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Note: Could not save last_run_report.json: {e}")

    if dry_run:
        root = config["project_root"]
        preview_file = root / "test_email.html"
        preview_file.write_text(html_body, encoding="utf-8")

        logger.info("\n" + "=" * 60)
        logger.info(" [DRY-RUN MODE] Zero SMTP or network calls made.")
        logger.info(f" HTML email preview written to: {preview_file}")
        logger.info("=" * 60 + "\n")
        logger.info(text_body)
        return preview_file, text_body

    if not config["email"].get("enabled", True):
        logger.info("Email notification is disabled in config.yaml. Skipping send.")
        return None, text_body

    send_email(subject, text_body, html_body, config, attachments)
    return None, text_body


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Morphe Patcher Email Dispatcher")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate and preview email content locally without sending via SMTP",
    )
    parser.add_argument(
        "--duration",
        type=str,
        default=None,
        help="Optional elapsed duration string (e.g. '3m 14s')",
    )
    args = parser.parse_args()

    # Deterministic test fixtures:
    test_success = {}

    project_root = Path(__file__).resolve().parent.parent
    macrodroid_apk = (
        project_root / "apps/patched/com.arlosoft.macrodroid/5.66.9/com.arlosoft.macrodroid_5.66.9_patched.apk"
    )
    if macrodroid_apk.is_file():
        test_success["com.arlosoft.macrodroid"] = {
            "dest": macrodroid_apk,
            "arch": "arm64-v8a",
            "strategy": 1,
            "attempt": 1,
            "scanned_repos": ["https://github.com/rushiranpise/morphe-patches"],
            "applied_repos": ["https://github.com/rushiranpise/morphe-patches"],
            "attempts": [],
        }

    duolingo_apk = (
        project_root / "apps/patched/com.duolingo/6.95.4/com.duolingo_6.95.4_patched.apk"
    )
    if duolingo_apk.is_file():
        test_success["com.duolingo"] = {
            "dest": duolingo_apk,
            "arch": "arm64-v8a",
            "strategy": 1,
            "attempt": 2,
            "scanned_repos": ["https://github.com/MorpheApp/morphe-patches", "https://github.com/hoo-dles/morphe-patches"],
            "applied_repos": ["https://github.com/hoo-dles/morphe-patches"],
            "attempts": [
                {
                    "version": "6.96.0",
                    "run": 1,
                    "stage": "Morphe Patching",
                    "reason": "Morphe CLI error: bytecode incompatible with all enabled patches",
                }
            ],
        }

    if not test_success:
        patched_apks = list(Path(__file__).resolve().parent.parent.glob("apps/patched/*/*/*_patched.apk"))
        for apk in patched_apks[:2]:
            pkg = apk.parent.parent.name
            test_success[pkg] = {
                "dest": apk,
                "arch": "arm64-v8a",
                "strategy": 1,
                "attempt": 1,
                "scanned_repos": ["https://github.com/rushiranpise/morphe-patches"],
                "applied_repos": ["https://github.com/rushiranpise/morphe-patches"],
                "attempts": [],
            }

    # 2. Simulated pipeline failure to showcase diagnostic grouping
    test_failures = {
        "com.google.android.youtube": {
            "target_versions": ["19.16.39", "19.11.43"],
            "arch": "arm64-v8a",
            "scanned_repos": ["https://github.com/MorpheApp/morphe-patches"],
            "applied_repos": ["https://github.com/MorpheApp/morphe-patches"],
            "attempts": [
                {
                    "version": "19.16.39",
                    "run": 1,
                    "stage": "Download / Verification",
                    "reason": "Base APK download/verification failed (arch arm64-v8a unavailable on APKPure)",
                },
                {
                    "version": "19.11.43",
                    "run": 1,
                    "stage": "Morphe Patching",
                    "reason": "Morphe CLI failed with version-specific patches fallback",
                },
            ],
        }
    }

    test_flags = {
        "striplibs": True,
        "architecture": "arm64-v8a",
        "low_spec_mode": False,
    }

    print("[dispatcher] Running dispatcher test fixture...")
    main(
        test_success,
        failures=test_failures,
        duration=args.duration or "3m 14s",
        dry_run=args.dry_run,
        build_flags=test_flags,
    )
