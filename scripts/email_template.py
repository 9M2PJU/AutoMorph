"""
Email template & rendering module for AutoMorph / Morphe Patcher.

Implements the Morphe Obsidian Cyber Synthetics design system faithfully to
web/frontend/css/morphe.css, featuring:
  - Dark obsidian surfaces (#0d0e12, #14161d, #1a1d26)
  - Morphe Electric Gradient banner (linear-gradient(90deg, #4A7FC8 0%, #20CFCE 100%))
  - Authentic service branding for download CTAs:
      * Cloudflare: #F38020 (Cloudflare Orange)
      * Pangolin:   #DC2626 (Crimson / Red)
      * Tailscale:  #121316 (Tailscale Black with #333A48 border)
      * Local:      #4A7FC8 (AutoMorph Theme Blue)
  - High-contrast, responsive dual-MIME (HTML + Plain Text) compatible with
    major email clients (Gmail, Apple Mail, Outlook).
"""

from __future__ import annotations

import argparse
from datetime import datetime
import html
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Service Brand Theming
# ---------------------------------------------------------------------------

SERVICE_THEMES: dict[str, dict[str, str]] = {
    "cloudflare": {
        "id": "cloudflare",
        "label": "Cloudflare",
        "badge": "CF",
        "icon": "☁️",
        "bg_color": "#F38020",
        "text_color": "#ffffff",
        "border_color": "#ea580c",
        "hover_color": "#ea580c",
    },
    "pangolin": {
        "id": "pangolin",
        "label": "Pangolin",
        "badge": "Pangolin",
        "icon": "🌐",
        "bg_color": "#DC2626",
        "text_color": "#ffffff",
        "border_color": "#b91c1c",
        "hover_color": "#b91c1c",
    },
    "tailscale": {
        "id": "tailscale",
        "label": "Tailscale",
        "badge": "Tailscale",
        "icon": "🔒",
        "bg_color": "#121316",
        "text_color": "#ffffff",
        "border_color": "#333A48",
        "hover_color": "#1e232d",
    },
    "local": {
        "id": "local",
        "label": "Local",
        "badge": "Local",
        "icon": "⚡",
        "bg_color": "#4A7FC8",
        "text_color": "#ffffff",
        "border_color": "#3b69a6",
        "hover_color": "#3b69a6",
    },
}


def get_service_theme(service_id: str) -> dict[str, str]:
    """Returns the visual styling tokens for a given service ID."""
    sid = str(service_id).lower().strip()
    return SERVICE_THEMES.get(sid, {
        "id": sid,
        "label": sid.capitalize(),
        "badge": sid.upper(),
        "icon": "⚡",
        "bg_color": "#4A7FC8",
        "text_color": "#ffffff",
        "border_color": "#3b69a6",
        "hover_color": "#3b69a6",
    })


# ---------------------------------------------------------------------------
# Formatting Helpers
# ---------------------------------------------------------------------------

def format_file_size(size_val: Any) -> str:
    """Formats file size from string, bytes integer, or None."""
    if size_val is None or size_val == "":
        return "Unknown size"
    if isinstance(size_val, str) and not size_val.isdigit():
        return size_val.strip()
    try:
        size_bytes = float(size_val)
    except (ValueError, TypeError):
        return "Unknown size"

    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}" if unit in ["MB", "GB"] else f"{int(size_bytes)} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def format_duration(duration: str | float | int | None) -> str:
    """Formats execution duration."""
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


def clean_repo_name(repo_url_or_name: str) -> str:
    """Normalizes a repo URL or name to 'owner/repo' or repo basename."""
    if not repo_url_or_name:
        return ""
    cleaned = str(repo_url_or_name).strip()
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    if ".com/" in cleaned:
        cleaned = cleaned.split(".com/")[1]
    elif ".org/" in cleaned:
        cleaned = cleaned.split(".org/")[1]
    cleaned = cleaned.strip("/")
    return cleaned


# ---------------------------------------------------------------------------
# Button Builders
# ---------------------------------------------------------------------------

def render_download_buttons_html(
    download_urls: dict[str, dict[str, Any]],
    file_size_str: str = "",
) -> str:
    """
    Renders high-contrast, email-safe download buttons styled to matching
    service brand colors (Cloudflare #F38020, Pangolin #DC2626, Tailscale #121316).
    """
    if not download_urls:
        return """
        <div style="margin-top: 12px; font-size: 11px; color: #64748b; font-style: italic; text-align: center;">
          Download link unavailable (file outside serve root)
        </div>
        """

    endpoints = list(download_urls.values())
    size_pill = (
        f'<span style="display: inline-block; background-color: rgba(0, 0, 0, 0.35); color: #ffffff !important; padding: 2px 7px; border-radius: 4px; margin-left: 6px; font-size: 11px; font-weight: 600;">{file_size_str}</span>'
        if file_size_str and file_size_str != "Unknown size"
        else ""
    )

    # Single Endpoint: Render a prominent full-width CTA button
    if len(endpoints) == 1:
        ep = endpoints[0]
        theme = get_service_theme(ep.get("id", ""))
        bg = ep.get("color") or theme["bg_color"]
        border = ep.get("border_color") or theme["border_color"]
        icon = ep.get("icon") or theme["icon"]
        label = ep.get("label") or theme["label"]

        return f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top: 14px;">
          <tr>
            <td align="center">
              <a href="{ep['url']}" target="_blank" style="display: block; width: 100%; box-sizing: border-box; background-color: {bg}; border: 1px solid {border}; color: #ffffff !important; text-decoration: none; font-size: 13px; font-weight: 700; text-align: center; padding: 11px 16px; border-radius: 8px; line-height: 1.3;">
                <span style="color: #ffffff !important;">{icon} Download via {label}</span>
                {size_pill}
              </a>
            </td>
          </tr>
        </table>
        """

    # Multiple Endpoints: Render side-by-side service buttons
    btn_cells = []
    width_pct = int(100 / len(endpoints))
    for ep in endpoints:
        theme = get_service_theme(ep.get("id", ""))
        bg = ep.get("color") or theme["bg_color"]
        border = ep.get("border_color") or theme["border_color"]
        icon = ep.get("icon") or theme["icon"]
        label = ep.get("label") or theme["label"]

        btn_cells.append(f"""
        <td class="stack-mobile" align="center" style="width: {width_pct}%; padding: 4px 5px;">
          <a href="{ep['url']}" target="_blank" style="display: block; box-sizing: border-box; background-color: {bg}; border: 1px solid {border}; color: #ffffff !important; text-decoration: none; font-size: 12px; font-weight: 700; text-align: center; padding: 10px 10px; border-radius: 8px; line-height: 1.3;">
            <span style="color: #ffffff !important;">{icon} {label}</span>
            {size_pill}
          </a>
        </td>
        """)

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top: 14px;">
      <tr>
        {''.join(btn_cells)}
      </tr>
    </table>
    """


def render_compact_download_buttons_html(download_urls: dict[str, dict[str, Any]]) -> str:
    """Renders small, compact download pills for the collapsed table row view."""
    if not download_urls:
        return '<span style="display: inline-block; background-color: #191b22; color: #64748b; border: 1px solid #232a3e; font-size: 10px; font-weight: 600; padding: 3px 8px; border-radius: 4px; font-family: ui-monospace, monospace;">Local Only</span>'

    endpoints = list(download_urls.values())
    if len(endpoints) == 1:
        ep = endpoints[0]
        theme = get_service_theme(ep.get("id", ""))
        bg = ep.get("color") or theme["bg_color"]
        icon = ep.get("icon") or theme["icon"]
        return f'<a href="{ep["url"]}" target="_blank" style="display: inline-block; background-color: {bg}; color: #ffffff !important; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 4px; text-decoration: none; white-space: nowrap;">{icon} Download</a>'

    items = []
    for ep in endpoints:
        theme = get_service_theme(ep.get("id", ""))
        bg = ep.get("color") or theme["bg_color"]
        icon = ep.get("icon") or theme["icon"]
        badge_lbl = ep.get("badge") or theme["badge"]
        items.append(
            f'<a href="{ep["url"]}" target="_blank" style="display: inline-block; background-color: {bg}; color: #ffffff !important; font-size: 10px; font-weight: 700; padding: 3px 7px; border-radius: 4px; text-decoration: none; white-space: nowrap; margin-left: 4px;">{icon} {badge_lbl}</a>'
        )
    return "".join(items)


# ---------------------------------------------------------------------------
# App Card Components
# ---------------------------------------------------------------------------

def render_success_app_card(app: dict[str, Any]) -> str:
    """
    Renders a single successful app card styled to Morphe Obsidian Cyber aesthetics.
    """
    patch_info = app.get("patch_info") or {}
    applied_patches = patch_info.get("applied_patches") or []
    failed_patches = patch_info.get("failed_patches") or []
    superseded_patches = patch_info.get("superseded_patches") or []
    unapplied_patches = patch_info.get("unapplied_patches") or []

    has_failed = len(failed_patches) > 0
    has_unapplied = len(unapplied_patches) > 0

    if has_failed:
        badge_bg_hdr = "rgba(239, 68, 68, 0.15)"
        badge_border_hdr = "rgba(239, 68, 68, 0.35)"
        badge_col_hdr = "#f87171"
        badge_label_hdr = f"{len(failed_patches)} Failed"
    elif has_unapplied:
        badge_bg_hdr = "rgba(245, 158, 11, 0.15)"
        badge_border_hdr = "rgba(245, 158, 11, 0.35)"
        badge_col_hdr = "#fbbf24"
        badge_label_hdr = f"{len(unapplied_patches)} Skipped"
    else:
        badge_bg_hdr = "rgba(16, 185, 129, 0.15)"
        badge_border_hdr = "rgba(16, 185, 129, 0.35)"
        badge_col_hdr = "#34d399"
        badge_label_hdr = "All Patches Applied"

    # Repository Tags
    repos_html = ""
    repos_list = app.get("applied_repos") or app.get("repos") or []
    if repos_list:
        repo_chips = "".join([
            f'<span style="display: inline-block; background-color: #1a1e2b; border: 1px solid #2a334a; border-radius: 4px; padding: 2px 7px; margin: 2px 3px; font-size: 11px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace; color: #7dd3fc;">📦 {clean_repo_name(r)}</span>'
            for r in repos_list if r
        ])
        repos_html = f"""
        <div style="margin-top: 10px; font-size: 11px; color: #94a3b8;">
          <strong style="color: #cbd5e1;">Patch Repositories:</strong> {repo_chips}
        </div>
        """

    # Checksum line (optional)
    checksum_html = ""
    if app.get("checksum"):
        checksum_html = f"""
        <tr>
          <td colspan="2" style="padding-top: 4px; font-size: 11px; color: #94a3b8;">
            SHA-256: <code style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; color: #cbd5e1; font-size: 10px; word-break: break-all;">{app['checksum']}</code>
          </td>
        </tr>
        """

    # Applied Patches Block
    applied_items_html = ""
    if applied_patches:
        chips = []
        for p in applied_patches:
            if isinstance(p, dict):
                p_name = p.get("name") or "Patch"
                p_repo = clean_repo_name(p.get("repo", ""))
            else:
                p_name = str(p)
                p_repo = ""
            repo_tag = f' <span style="color: #64748b; font-size: 10px;">({p_repo})</span>' if p_repo else ""
            chips.append(
                f'<span style="display: inline-block; background-color: #121e1d; border: 1px solid #1c3833; border-radius: 4px; padding: 2px 6px; margin: 2px 2px; font-size: 11px; color: #6ee7b7; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace;">'
                f'<span style="color: #10b981; font-weight: bold; margin-right: 3px;">✓</span>{html.escape(p_name)}{repo_tag}</span>'
            )
        applied_items_html = f"""
        <div style="margin-top: 10px; background-color: #0c0e14; border: 1px solid #1a2724; border-left: 3px solid #10b981; border-radius: 6px; padding: 8px 10px;">
          <div style="font-size: 11px; font-weight: 700; color: #34d399; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">
            Applied Patches ({len(applied_patches)})
          </div>
          <div style="line-height: 20px;">
            {''.join(chips)}
          </div>
        </div>
        """

    # Explicitly Failed Patches Block (if any)
    failed_items_html = ""
    if failed_patches:
        f_rows = []
        for fp in failed_patches:
            f_name = fp.get("name") if isinstance(fp, dict) else str(fp)
            f_reason = fp.get("reason", "Patch execution error") if isinstance(fp, dict) else ""
            f_rows.append(
                f'<div style="font-size: 11px; color: #fca5a5; margin-top: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace;">'
                f'  <strong style="color: #f87171;">✕ {html.escape(f_name)}:</strong> {html.escape(f_reason)}'
                f'</div>'
            )
        failed_items_html = f"""
        <div style="margin-top: 8px; background-color: #0c0e14; border: 1px solid #331f24; border-left: 3px solid #ef4444; border-radius: 6px; padding: 8px 10px;">
          <div style="font-size: 11px; font-weight: 700; color: #f87171; text-transform: uppercase; letter-spacing: 0.5px;">
            Failed Patches ({len(failed_patches)})
          </div>
          {''.join(f_rows)}
        </div>
        """

    # Download Buttons (Service Branded)
    download_buttons_html = render_download_buttons_html(
        download_urls=app.get("download_urls") or {},
        file_size_str=app.get("file_size", ""),
    )

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #141720; border: 1px solid #1f2d2b; border-radius: 12px; overflow: hidden; border-top: 2px solid #10b981; margin-bottom: 16px;">
      <tr>
        <td style="padding: 16px 18px;">
          <!-- Package Header Bar -->
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr>
              <td class="stack-mobile" align="left" valign="middle">
                <span style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 15px; font-weight: 700; color: #f8fafc;">{html.escape(app['package'])}</span>
                <span style="display: inline-block; background-color: rgba(56, 189, 248, 0.15); color: #7dd3fc; border: 1px solid rgba(56, 189, 248, 0.3); font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 4px; margin-left: 6px;">v{html.escape(str(app.get('version', '')))}</span>
                <span style="display: inline-block; background-color: rgba(148, 163, 184, 0.12); color: #cbd5e1; border: 1px solid #232a3e; font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 4px; margin-left: 6px; font-family: ui-monospace, monospace;">{html.escape(str(app.get('arch', '')))}</span>
                <span style="display: inline-block; background-color: rgba(56, 189, 248, 0.12); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 4px; margin-left: 6px; font-family: ui-monospace, monospace;">{html.escape(str(app.get('winning_badge', 'Strategy 1 • Attempt 1')))}</span>
              </td>
              <td class="stack-mobile-right" align="right" valign="middle">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="background-color: {badge_bg_hdr}; border: 1px solid {badge_border_hdr}; border-radius: 9999px;">
                  <tr>
                    <td style="padding: 3px 10px; text-align: center;">
                      <div style="font-size: 10px; font-weight: 800; color: {badge_col_hdr}; text-transform: uppercase; letter-spacing: 0.3px;">{badge_label_hdr}</div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>

          <!-- File & Build Meta -->
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top: 10px;">
            <tr>
              <td align="left" style="font-size: 12px; color: #94a3b8;">
                Output APK: <code style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; color: #e2e8f0; background-color: #0c0e14; padding: 2px 7px; border-radius: 4px; border: 1px solid #1f2330;">{html.escape(app.get('filename', ''))}</code>
              </td>
              <td align="right" style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; color: #94a3b8; font-weight: 600;">
                {html.escape(app.get('file_size', ''))}
              </td>
            </tr>
            <tr>
              <td colspan="2" style="padding-top: 4px; font-size: 11px; color: #94a3b8;">
                Build Resolution: <strong style="color: #7dd3fc; font-family: ui-monospace, monospace;">{html.escape(str(app.get('winning_full', 'Strategy 1 (All Patches) • Attempt 1')))}</strong>
              </td>
            </tr>
            {checksum_html}
          </table>

          {repos_html}
          {applied_items_html}
          {failed_items_html}
          {download_buttons_html}
        </td>
      </tr>
    </table>
    """


def render_compact_success_row(app: dict[str, Any]) -> str:
    """Renders a single compact row for condensed email overviews."""
    patch_info = app.get("patch_info") or {}
    has_failed = len(patch_info.get("failed_patches", [])) > 0
    has_unapplied = len(patch_info.get("unapplied_patches", [])) > 0

    if has_failed:
        row_border = "#ef4444"
        status_chip = f'<span style="display: inline-block; background-color: rgba(239, 68, 68, 0.15); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.3); font-size: 9px; font-weight: 700; padding: 1px 6px; border-radius: 3px; text-transform: uppercase;">{len(patch_info["failed_patches"])} FAILED</span>'
    elif has_unapplied:
        row_border = "#f59e0b"
        status_chip = f'<span style="display: inline-block; background-color: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); font-size: 9px; font-weight: 700; padding: 1px 6px; border-radius: 3px; text-transform: uppercase;">{len(patch_info.get("applied_patches", []))} OK &bull; {len(patch_info["unapplied_patches"])} SKIPPED</span>'
    else:
        row_border = "#10b981"
        status_chip = f'<span style="display: inline-block; background-color: rgba(16, 185, 129, 0.15); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.3); font-size: 9px; font-weight: 700; padding: 1px 6px; border-radius: 3px; text-transform: uppercase;">{len(patch_info.get("applied_patches", []))} PATCHES</span>'

    compact_btn = render_compact_download_buttons_html(app.get("download_urls") or {})

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #141720; border: 1px solid #1f2533; border-left: 3px solid {row_border}; border-radius: 8px; margin-bottom: 8px;">
      <tr>
        <td style="padding: 10px 14px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr>
              <td class="stack-mobile" align="left" valign="middle">
                <span style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 13px; font-weight: 700; color: #f1f5f9;">{html.escape(app['package'])}</span>
                <span style="display: inline-block; background-color: rgba(56, 189, 248, 0.12); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 3px; margin-left: 4px; font-family: ui-monospace, monospace;">v{html.escape(str(app.get('version', '')))}</span>
                <span style="display: inline-block; background-color: rgba(148, 163, 184, 0.12); color: #cbd5e1; border: 1px solid #232a3e; font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 3px; margin-left: 4px; font-family: ui-monospace, monospace;">{html.escape(str(app.get('arch', '')))}</span>
                <span style="font-size: 11px; color: #64748b; margin-left: 4px; font-family: ui-monospace, monospace;">{html.escape(app.get('file_size', ''))}</span>
                <span style="margin-left: 4px;">{status_chip}</span>
              </td>
              <td class="stack-mobile-right" align="right" valign="middle" style="padding-left: 8px;">
                {compact_btn}
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
    """


def render_failure_card(fail: dict[str, Any]) -> str:
    """Renders a failure card with diagnostic attempt history."""
    attempts_rows = []
    grouped_attempts = fail.get("grouped_attempts") or {}

    for ver, att_list in grouped_attempts.items():
        sub_items = []
        for att in att_list:
            stage = str(att.get("stage", "GENERAL")).upper()
            strat_label = f"STRATEGY {att.get('run', 1)}"
            reason = html.escape(str(att.get("reason", "Unknown failure")))
            badge_bg = "rgba(239, 68, 68, 0.2)" if "DOWNLOAD" in stage else "rgba(245, 158, 11, 0.2)"
            badge_col = "#f87171" if "DOWNLOAD" in stage else "#fbbf24"

            sub_items.append(f"""
            <div style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace; font-size: 12px; color: #cbd5e1; margin-top: 6px; line-height: 1.4;">
              <span style="display: inline-block; background-color: {badge_bg}; color: {badge_col}; font-weight: 700; padding: 1px 5px; border-radius: 3px; font-size: 10px;">{stage} &bull; {strat_label}</span>
              {reason}
            </div>
            """)

        attempts_rows.append(f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #0c0e14; border: 1px solid #231c22; border-left: 3px solid #ef4444; border-radius: 6px; margin-bottom: 8px;">
          <tr>
            <td style="padding: 10px 12px;">
              <span style="font-family: ui-monospace, monospace; font-size: 12px; font-weight: 700; color: #fca5a5;">Target v{html.escape(str(ver))}</span>
              {''.join(sub_items)}
            </td>
          </tr>
        </table>
        """)

    targets_str = ", ".join(fail.get("target_versions", [])) or "None specified"

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #1a1418; border: 1px solid #3d2328; border-radius: 12px; overflow: hidden; border-top: 2px solid #ef4444; margin-bottom: 16px;">
      <tr>
        <td style="padding: 16px 18px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr>
              <td align="left">
                <span style="font-family: ui-monospace, monospace; font-size: 15px; font-weight: 700; color: #fee2e2;">{html.escape(fail['package'])}</span>
                <span style="display: inline-block; background-color: rgba(239, 68, 68, 0.2); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.4); font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 4px; margin-left: 6px;">Pipeline Failure</span>
              </td>
            </tr>
          </table>
          <div style="font-size: 12px; color: #94a3b8; margin-top: 8px; margin-bottom: 10px;">
            Target Versions Attempted: <strong style="color: #cbd5e1;">{html.escape(targets_str)}</strong>
          </div>
          {''.join(attempts_rows)}
        </td>
      </tr>
    </table>
    """


# ---------------------------------------------------------------------------
# Full Document Assembler
# ---------------------------------------------------------------------------

def assemble_email_html(
    subject: str,
    badge_text: str,
    badge_bg: str,
    badge_border: str,
    badge_dot: str,
    badge_color: str,
    now_str: str,
    host_display: str,
    total_success: int,
    total_failures: int,
    duration_str: str,
    success_records: list[dict[str, Any]],
    failure_records: list[dict[str, Any]],
    build_flags: dict[str, Any] | None = None,
    web_report_endpoints: list[dict[str, Any]] | None = None,
    is_compact: bool = False,
    security_badge_text: str = "Tunnels Active",
    raw_log_str: str | None = None,
) -> str:
    """
    Assembles the complete responsive HTML document in Morphe Obsidian Cyber Synthetics styling.
    """
    build_flags = build_flags or {}
    web_report_endpoints = web_report_endpoints or []

    # Web report links header
    if len(web_report_endpoints) > 1:
        links = []
        for ep in web_report_endpoints:
            if ep.get("url"):
                theme = get_service_theme(ep.get("id", ""))
                color = theme["bg_color"] if theme["id"] != "tailscale" else "#38bdf8"
                links.append(f'<a href="{ep["url"]}" target="_blank" style="font-size: 12px; color: {color}; text-decoration: none; font-weight: 600;">{ep.get("label", "Report")}</a>')
        web_link_hdr = (
            f'<span style="font-size: 12px; color: #475569; padding: 0 4px;">&bull;</span>'
            f'<span style="font-size: 12px; color: #94a3b8; font-weight: 600;">🌐 Portals: </span>'
            + ' <span style="font-size: 11px; color: #475569; padding: 0 2px;">|</span> '.join(links)
        )
    elif web_report_endpoints and web_report_endpoints[0].get("url"):
        ep = web_report_endpoints[0]
        web_link_hdr = (
            f'<span style="font-size: 12px; color: #475569; padding: 0 4px;">&bull;</span>'
            f'<a href="{ep["url"]}" target="_blank" style="font-size: 12px; color: #20CFCE; text-decoration: none; font-weight: 600;">🌐 Web Portal &rarr;</a>'
        )
    else:
        web_link_hdr = ""

    # Chips for Top Summary Boxes
    if success_records:
        succeeded_chips = "".join(
            f'<span style="display: inline-block; background-color: #162026; border: 1px solid #23373e; border-radius: 9999px; padding: 2px 8px; margin: 2px 3px 2px 0; font-size: 11px; line-height: 16px; color: #cbd5e1;">'
            f'<span style="color: #34d399; font-weight: bold; margin-right: 4px;">&bull;</span>{html.escape(app["package"])}</span>'
            for app in success_records
        )
        succeeded_chips_html = f'<div style="margin-top: 8px; line-height: 20px;">{succeeded_chips}</div>'
    else:
        succeeded_chips_html = '<div style="margin-top: 6px; font-size: 11px; color: #64748b;">None</div>'

    if failure_records:
        failed_chips = "".join(
            f'<span style="display: inline-block; background-color: #241618; border: 1px solid #4a2327; border-radius: 9999px; padding: 2px 8px; margin: 2px 3px 2px 0; font-size: 11px; line-height: 16px; color: #fca5a5;">'
            f'<span style="color: #ef4444; font-weight: bold; margin-right: 4px;">&bull;</span>{html.escape(fail["package"])}</span>'
            for fail in failure_records
        )
        failed_chips_html = f'<div style="margin-top: 8px; line-height: 20px;">{failed_chips}</div>'
    else:
        failed_chips_html = '<div style="margin-top: 6px; font-size: 11px; color: #64748b;">None</div>'

    # Build Flags Section
    arch_val = build_flags.get("architecture", "arm64-v8a")
    striplibs_val = build_flags.get("striplibs", True)
    low_spec_val = build_flags.get("low_spec_mode", True)

    striplibs_chip = (
        f'<span style="display: inline-block; background-color: rgba(32, 207, 206, 0.12); color: #20CFCE; border: 1px solid rgba(32, 207, 206, 0.3); border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: 600; font-family: ui-monospace, monospace; margin: 2px 3px;">striplibs: <strong>{arch_val}</strong></span>'
        if striplibs_val
        else '<span style="display: inline-block; background-color: #191b22; color: #64748b; border: 1px solid #232a3e; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-family: ui-monospace, monospace; margin: 2px 3px;">striplibs: off</span>'
    )
    low_spec_chip = (
        '<span style="display: inline-block; background-color: rgba(245, 158, 11, 0.12); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: 600; font-family: ui-monospace, monospace; margin: 2px 3px;">low-spec: active</span>'
        if low_spec_val
        else '<span style="display: inline-block; background-color: #191b22; color: #64748b; border: 1px solid #232a3e; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-family: ui-monospace, monospace; margin: 2px 3px;">low-spec: off</span>'
    )
    arch_chip = f'<span style="display: inline-block; background-color: #191b22; color: #cbd5e1; border: 1px solid #232a3e; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-family: ui-monospace, monospace; margin: 2px 3px;">arch: <strong>{arch_val}</strong></span>'

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

    # Failures Section
    if failure_records:
        fail_cards = "".join([render_failure_card(f) for f in failure_records])
        failures_section_html = f"""
        <tr>
          <td style="padding: 16px 28px 0 28px;" class="content-padding">
            <div style="font-size: 13px; font-weight: 700; color: #f87171; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 12px;">
              ⚠️ Severe Pipeline Failures ({total_failures})
            </div>
            {fail_cards}
          </td>
        </tr>
        """
    else:
        failures_section_html = ""

    # Success Section (Full Cards vs Compact Rows)
    if success_records:
        if is_compact:
            success_rows = "".join([render_compact_success_row(a) for a in success_records])
            success_section_html = f"""
            <tr>
              <td style="padding: 16px 28px 0 28px;" class="content-padding">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 10px;">
                  <tr>
                    <td align="left">
                      <span style="font-size: 13px; font-weight: 700; color: #34d399; text-transform: uppercase; letter-spacing: 0.5px;">
                        ✔ Ready for Download ({total_success})
                      </span>
                    </td>
                    <td align="right">
                      <span style="font-size: 11px; color: #94a3b8; font-family: ui-monospace, monospace;">compact overview</span>
                    </td>
                  </tr>
                </table>
                {success_rows}
              </td>
            </tr>
            """
        else:
            success_cards = "".join([render_success_app_card(a) for a in success_records])
            success_section_html = f"""
            <tr>
              <td style="padding: 16px 28px 0 28px;" class="content-padding">
                <div style="font-size: 13px; font-weight: 700; color: #34d399; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 12px;">
                  ✔ Ready for Download ({total_success})
                </div>
                {success_cards}
              </td>
            </tr>
            """
    else:
        success_section_html = ""

    # Optional Log Section
    if raw_log_str:
        log_section_html = f"""
        <tr>
          <td style="padding: 14px 28px;" class="content-padding">
            <div style="font-size: 12px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">
              📋 Pipeline Execution Log
            </div>
            <pre style="background-color: #0c0e14; border: 1px solid #1f2330; border-radius: 8px; padding: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace; font-size: 10px; color: #cbd5e1; max-height: 240px; overflow-y: auto; white-space: pre-wrap; word-break: break-all;">{html.escape(raw_log_str)}</pre>
          </td>
        </tr>
        """
    else:
        log_section_html = ""

    # Mirror Portal links in footer
    footer_portals = ""
    if web_report_endpoints:
        portal_links = []
        for ep in web_report_endpoints:
            theme = get_service_theme(ep.get("id", ""))
            portal_links.append(f'<a href="{ep["url"]}" target="_blank" style="color: #20CFCE; text-decoration: none; font-weight: 600; margin: 0 6px;">{theme["icon"]} {ep["label"]}</a>')
        footer_portals = f"""
        <div style="margin-top: 10px; font-size: 11px; color: #64748b;">
          Direct Web Access: {' | '.join(portal_links)}
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
  <meta charset="utf-8">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="dark">
  <meta name="supported-color-schemes" content="dark">
  <title>{subject}</title>
  <style type="text/css">
    body, p, h1, h2, h3, div, table, td {{ margin: 0; padding: 0; }}
    body {{
      -webkit-text-size-adjust: 100%;
      -ms-text-size-adjust: 100%;
      background-color: #0d0e12;
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    }}
    table, td {{
      mso-table-lspace: 0pt;
      mso-table-rspace: 0pt;
      border-collapse: collapse;
    }}
    @media only screen and (max-width: 640px) {{
      .email-container {{ width: 100% !important; max-width: 100% !important; }}
      .metric-col {{ display: block !important; width: 100% !important; margin-bottom: 8px !important; box-sizing: border-box !important; }}
      .stack-mobile {{ display: block !important; width: 100% !important; text-align: left !important; }}
      .stack-mobile-right {{ display: block !important; width: 100% !important; text-align: left !important; margin-top: 6px !important; }}
      .content-padding {{ padding-left: 16px !important; padding-right: 16px !important; }}
    }}
  </style>
</head>
<body style="margin: 0; padding: 0; background-color: #0d0e12; color: #f3f4f6; -webkit-font-smoothing: antialiased;">

  <!-- Preheader snippet -->
  <div style="display: none; font-size: 1px; color: #0d0e12; line-height: 1px; max-height: 0px; max-width: 0px; opacity: 0; overflow: hidden; mso-hide: all;">
    AutoMorph: {total_success} succeeded, {total_failures} failed &zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;
  </div>

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#0d0e12" style="background-color: #0d0e12; table-layout: fixed;">
    <tr>
      <td align="center" style="padding: 24px 12px 36px 12px;">

        <!-- Main Card Container -->
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="email-container" style="max-width: 620px; width: 100%; margin: 0 auto; background-color: #14161d; border: 1px solid #222632; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.7);">

          <!-- Morphe Electric Signature Top Border -->
          <tr>
            <td style="height: 3px; background: linear-gradient(90deg, #4A7FC8 0%, #20CFCE 100%); line-height: 3px; font-size: 1px;">&nbsp;</td>
          </tr>

          <!-- Brand Header -->
          <tr>
            <td style="padding: 24px 28px 16px 28px;" class="content-padding">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="border-bottom: 1px solid #1f2330; padding-bottom: 16px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                      <tr>
                        <td class="stack-mobile">
                          <div style="font-size: 18px; font-weight: 800; color: #ffffff; letter-spacing: -0.3px;">
                            AutoMorph <span style="display: inline-block; width: 8px; height: 8px; background-color: #20CFCE; border-radius: 50%; margin-left: 2px;"></span>
                          </div>
                          <div style="font-size: 12px; color: #9ca3af; margin-top: 3px;">
                            <span>{now_str}</span>
                            {web_link_hdr}
                          </div>
                        </td>
                        <td class="stack-mobile-right" align="right" valign="middle">
                          <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="right" style="background-color: {badge_bg}; border: 1px solid {badge_border}; border-radius: 9999px;">
                            <tr>
                              <td style="padding: 4px 12px;">
                                <span style="display: inline-block; width: 6px; height: 6px; background-color: {badge_dot}; border-radius: 50%; margin-right: 6px; vertical-align: middle;"></span>
                                <span style="font-size: 11px; font-weight: 700; color: {badge_color}; text-transform: uppercase; letter-spacing: 0.5px; vertical-align: middle;">{badge_text}</span>
                              </td>
                            </tr>
                          </table>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Summary Metric Cards -->
          <tr>
            <td style="padding: 0 28px 12px 28px;" class="content-padding">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <!-- Succeeded Box -->
                  <td class="metric-col" width="49%" style="vertical-align: top;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #101918; border: 1px solid #1c362d; border-radius: 10px;">
                      <tr>
                        <td style="padding: 14px 16px;">
                          <div style="font-size: 11px; font-weight: 700; color: #34d399; text-transform: uppercase; letter-spacing: 0.5px;">
                            Succeeded
                          </div>
                          <div style="font-size: 26px; font-weight: 800; color: #10b981; margin-top: 2px;">
                            {total_success}
                          </div>
                          {succeeded_chips_html}
                        </td>
                      </tr>
                    </table>
                  </td>
                  <td width="2%" style="font-size: 1px; line-height: 1px;">&nbsp;</td>
                  <!-- Failures Box -->
                  <td class="metric-col" width="49%" style="vertical-align: top;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #1a1215; border: 1px solid #3d1c23; border-radius: 10px;">
                      <tr>
                        <td style="padding: 14px 16px;">
                          <div style="font-size: 11px; font-weight: 700; color: #f87171; text-transform: uppercase; letter-spacing: 0.5px;">
                            Pipeline Failures
                          </div>
                          <div style="font-size: 26px; font-weight: 800; color: #ef4444; margin-top: 2px;">
                            {total_failures}
                          </div>
                          {failed_chips_html}
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Meta Pill Row -->
          <tr>
            <td style="padding: 0 28px 14px 28px;" class="content-padding">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #12151e; border: 1px solid #1f2533; border-radius: 8px;">
                <tr>
                  <td style="padding: 9px 14px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                      <tr>
                        <td class="stack-mobile" align="left">
                          <span style="font-size: 11px; color: #94a3b8;">
                            Host: <strong style="color: #cbd5e1; font-family: ui-monospace, monospace;">{host_display}</strong>
                          </span>
                        </td>
                        <td class="stack-mobile-right" align="right">
                          <span style="font-size: 11px; color: #94a3b8; margin-right: 8px;">
                            Elapsed: <strong style="color: #cbd5e1; font-family: ui-monospace, monospace;">{duration_str}</strong>
                          </span>
                          <span style="display: inline-block; background-color: rgba(32, 207, 206, 0.12); color: #20CFCE; border: 1px solid rgba(32, 207, 206, 0.3); font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 9999px;">{security_badge_text}</span>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          {general_flags_section_html}
          {failures_section_html}
          {success_section_html}
          {log_section_html}

          <!-- Footer Block -->
          <tr>
            <td style="padding: 24px 28px; border-top: 1px solid #1f2330; text-align: center;" class="content-padding">
              <div style="font-size: 12px; color: #94a3b8; font-weight: 600;">
                AutoMorph &bull; Automated ReVanced Morphe Pipeline
              </div>
              <div style="font-size: 11px; color: #64748b; margin-top: 4px;">
                Generated securely &bull; Notification dispatched via dual-MIME delivery
              </div>
              {footer_portals}
            </td>
          </tr>

        </table>

      </td>
    </tr>
  </table>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# Plain-Text Assembler
# ---------------------------------------------------------------------------

def assemble_plain_text(
    now_str: str,
    host_display: str,
    total_success: int,
    total_failures: int,
    duration_str: str,
    success_records: list[dict[str, Any]],
    failure_records: list[dict[str, Any]],
    build_flags: dict[str, Any] | None = None,
    web_report_endpoints: list[dict[str, Any]] | None = None,
    raw_log_str: str | None = None,
) -> str:
    """Assembles the clean plain-text fallback email body."""
    build_flags = build_flags or {}
    web_report_endpoints = web_report_endpoints or []

    succeeded_names = f" ({', '.join(a['package'] for a in success_records)})" if success_records else ""
    failed_names = f" ({', '.join(f['package'] for f in failure_records)})" if failure_records else ""

    text_lines = [
        "============================================================",
        " AUTOMORPH - BUILD REPORT",
        "============================================================",
        f"Build Date        : {now_str}",
        f"Host              : {host_display}",
    ]

    for ep in web_report_endpoints:
        text_lines.append(f"Web Portal ({ep['label']}): {ep['url']}")

    text_lines.extend([
        f"Apps Patched      : {total_success}{succeeded_names}",
        f"Pipeline Failures : {total_failures}{failed_names}",
        f"Duration          : {duration_str}",
        "",
        "BUILD CONFIGURATION & GENERAL FLAGS:",
        f"  Target Arch     : {build_flags.get('architecture', 'arm64-v8a')}",
        f"  Strip Libs      : {'Enabled' if build_flags.get('striplibs', True) else 'Disabled'}",
        f"  Low-Spec Mode   : {'Active' if build_flags.get('low_spec_mode', True) else 'Standard'}",
        "",
    ])

    if failure_records:
        text_lines.append("------------------------------------------------------------")
        text_lines.append(" SEVERE PIPELINE FAILURES")
        text_lines.append("------------------------------------------------------------")
        for i, fail in enumerate(failure_records, 1):
            targets = ", ".join(fail.get("target_versions", [])) or "None specified"
            text_lines.append(f"[{i}] {fail['package']}")
            text_lines.append(f"    Target Versions : {targets}")
            text_lines.append(f"    Architecture    : {fail.get('arch', 'arm64-v8a')}")
            for ver, att_list in (fail.get("grouped_attempts") or {}).items():
                text_lines.append(f"    * Target v{ver}:")
                for att in att_list:
                    stage = str(att.get("stage", "General")).upper()
                    strat = f"Strategy {att.get('run', 1)}"
                    reason = att.get("reason", "Unknown failure")
                    text_lines.append(f"      - [{stage}] ({strat}): {reason}")
            text_lines.append("")

    if success_records:
        text_lines.append("------------------------------------------------------------")
        text_lines.append(" READY FOR DOWNLOAD (SUCCESSFUL BUILDS)")
        text_lines.append("------------------------------------------------------------")
        for i, app in enumerate(success_records, 1):
            text_lines.append(f"[{i}] {app['package']} (v{app.get('version', '')})")
            text_lines.append(f"    Architecture    : {app.get('arch', '')}")
            text_lines.append(f"    File            : {app.get('filename', '')} ({app.get('file_size', '')})")
            if app.get("checksum"):
                text_lines.append(f"    SHA-256         : {app['checksum']}")
            dl_urls = app.get("download_urls") or {}
            for ep_id, ep_info in dl_urls.items():
                text_lines.append(f"    Download ({ep_info['label']}): {ep_info['url']}")
            patch_info = app.get("patch_info") or {}
            applied = patch_info.get("applied_patches") or []
            if applied:
                text_lines.append(f"    Applied Patches ({len(applied)}):")
                for p in applied:
                    p_name = p.get("name") if isinstance(p, dict) else str(p)
                    text_lines.append(f"      + {p_name}")
            text_lines.append("")

    if raw_log_str:
        text_lines.append("------------------------------------------------------------")
        text_lines.append(" EXECUTION LOG")
        text_lines.append("------------------------------------------------------------")
        text_lines.append(raw_log_str)
        text_lines.append("")

    text_lines.append("============================================================")
    return "\n".join(text_lines)


# ---------------------------------------------------------------------------
# CLI Preview Runner
# ---------------------------------------------------------------------------

def generate_sample_data() -> dict[str, Any]:
    """Generates realistic sample data across Cloudflare, Pangolin, and Tailscale."""
    download_urls = {
        "cloudflare": {
            "id": "cloudflare",
            "label": "Cloudflare",
            "badge": "CF",
            "icon": "☁️",
            "color": "#F38020",
            "url": "https://patcher.example.com/files/com.reddit.frontpage/2026.42.0/com.reddit.frontpage_2026.42.0_patched.apk",
        },
        "pangolin": {
            "id": "pangolin",
            "label": "Pangolin",
            "badge": "Pangolin",
            "icon": "🌐",
            "color": "#DC2626",
            "url": "https://pangolin.example.com/files/com.reddit.frontpage/2026.42.0/com.reddit.frontpage_2026.42.0_patched.apk",
        },
        "tailscale": {
            "id": "tailscale",
            "label": "Tailscale",
            "badge": "Tailscale",
            "icon": "🔒",
            "color": "#121316",
            "url": "https://patcher-funnel.ts.net/files/com.reddit.frontpage/2026.42.0/com.reddit.frontpage_2026.42.0_patched.apk",
        },
    }

    duo_urls = {
        "cloudflare": {
            "id": "cloudflare",
            "label": "Cloudflare",
            "badge": "CF",
            "icon": "☁️",
            "color": "#F38020",
            "url": "https://patcher.example.com/files/com.duolingo/6.98.4/com.duolingo_6.98.4_patched.apk",
        },
        "tailscale": {
            "id": "tailscale",
            "label": "Tailscale",
            "badge": "Tailscale",
            "icon": "🔒",
            "color": "#121316",
            "url": "https://patcher-funnel.ts.net/files/com.duolingo/6.98.4/com.duolingo_6.98.4_patched.apk",
        },
    }

    success_records = [
        {
            "package": "com.reddit.frontpage",
            "version": "2026.42.0",
            "arch": "arm64-v8a",
            "filename": "com.reddit.frontpage_2026.42.0_patched.apk",
            "file_size": "78.4 MB",
            "checksum": "d04ba078b0ca909a101765da286c4f31bb260945708b0baa54068442b1e4a452",
            "applied_repos": ["MorpheApp/morphe-patches", "jkennethcarino/adobo"],
            "winning_badge": "Strategy 1 • Attempt 1",
            "winning_full": "Strategy 1 (All Patches) • Attempt 1 (Target Version)",
            "download_urls": download_urls,
            "patch_info": {
                "applied_patches": [
                    {"name": "App icon", "repo": "MorpheApp"},
                    {"name": "Colorize comment indent lines", "repo": "jkennethcarino"},
                    {"name": "Custom font", "repo": "MorpheApp"},
                    {"name": "Disable screenshot popup", "repo": "MorpheApp"},
                    {"name": "Hide ads", "repo": "MorpheApp"},
                    {"name": "Sanitize share links", "repo": "jkennethcarino"},
                ],
                "failed_patches": [],
                "unapplied_patches": [],
            },
        },
        {
            "package": "com.duolingo",
            "version": "6.98.4",
            "arch": "arm64-v8a",
            "filename": "com.duolingo_6.98.4_patched.apk",
            "file_size": "42.1 MB",
            "checksum": "3280a40f8d09c49e3822ae6077c2f29742bad62fb4c0df5f707e6d4b30cc0d03",
            "applied_repos": ["hoo-dles/morphe-patches"],
            "winning_badge": "Strategy 1 • Attempt 1",
            "winning_full": "Strategy 1 (All Patches) • Attempt 1",
            "download_urls": duo_urls,
            "patch_info": {
                "applied_patches": [
                    {"name": "Enable Premium", "repo": "hoo-dles"},
                ],
                "failed_patches": [],
                "unapplied_patches": [],
            },
        },
    ]

    failure_records = [
        {
            "package": "com.ovelin.guitartuna",
            "arch": "arm64-v8a",
            "target_versions": ["7.14.2"],
            "grouped_attempts": {
                "7.14.2": [
                    {"stage": "OPTIONS", "run": 1, "reason": "No compatible patch bundle found for target version"},
                ]
            },
        }
    ]

    web_endpoints = [
        {"id": "cloudflare", "label": "Cloudflare Portal", "url": "https://patcher.example.com/"},
        {"id": "pangolin", "label": "Pangolin Portal", "url": "https://pangolin.example.com/"},
        {"id": "tailscale", "label": "Tailscale Funnel", "url": "https://patcher-funnel.ts.net/"},
    ]

    return {
        "subject": "[AutoMorph] 🚀 2 Apps Patched Successfully, 1 Pipeline Failure",
        "badge_text": "Partial Pass",
        "badge_bg": "rgba(245, 158, 11, 0.15)",
        "badge_border": "rgba(245, 158, 11, 0.35)",
        "badge_dot": "#f59e0b",
        "badge_color": "#fbbf24",
        "now_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "host_display": "patcher.example.com • patcher-funnel.ts.net",
        "total_success": len(success_records),
        "total_failures": len(failure_records),
        "duration_str": "1m 24s",
        "success_records": success_records,
        "failure_records": failure_records,
        "build_flags": {"architecture": "arm64-v8a", "striplibs": True, "low_spec_mode": True},
        "web_report_endpoints": web_endpoints,
        "is_compact": False,
        "security_badge_text": "Cloudflare & Tailscale Tunnels",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AutoMorph Email Template Preview Generator")
    parser.add_argument("--preview", action="store_true", help="Generate test_email.html with sample data")
    args = parser.parse_args()

    sample = generate_sample_data()
    html_content = assemble_email_html(**sample)

    output_path = Path(__file__).resolve().parent.parent / "tools" / "automorph-data" / "state" / "reports" / "test_email.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")
    print(f"Successfully generated email preview at: {output_path}")
