[🏠 Documentation Hub](README.md) › **User Guide & Configuration**

---

# AutoMorph User Guide & Configuration

Welcome to the AutoMorph user guide! This document explains how to use the web interface to configure packages, customize patch options, manage build schedules, and download patched APKs.

---

## Table of Contents

- [1. Web Interface Overview](#1-web-interface-overview)
- [2. Adding & Managing Packages](#2-adding--managing-packages)
  - [2.1 Add Package Wizard](#21-add-package-wizard)
  - [2.2 Choosing Patch Repositories](#22-choosing-patch-repositories)
  - [2.3 Enabling and Disabling Apps](#23-enabling-and-disabling-apps)
- [3. Customizing Patch Options](#3-customizing-patch-options)
- [4. Triggering Builds](#4-triggering-builds)
  - [4.1 Manual Single or Batch Builds](#41-manual-single-or-batch-builds)
  - [4.2 Scheduled Automated Builds](#42-scheduled-automated-builds)
- [5. System & Performance Settings](#5-system--performance-settings)
  - [5.1 Low-Spec Mode (Recommended for Free Tier)](#51-low-spec-mode-recommended-for-free-tier)
  - [5.2 Timezone & Schedule Time](#52-timezone--schedule-time)
  - [5.3 Retention & Storage Cleanup](#53-retention--storage-cleanup)
- [6. Email Dispatcher & Notifications](#6-email-dispatcher--notifications)
- [7. Downloading Builds](#7-downloading-builds)

---

## 1. Web Interface Overview

Once you navigate to your AutoMorph portal (via your [configured tunnel](tunnels.md) or local address), the dashboard displays:
* **System Status & Stats**: Total tracked packages, last build timestamp, and next scheduled run.
* **Tracked Applications List**: Cards showing version numbers, current patch status, and download links.
* **Console & Real-time Logs**: Live build status streamed directly to your browser when a build is underway.

---

## 2. Adding & Managing Packages

### 2.1 Add Package Wizard
1. On the dashboard, click **Add Package** (or **+**).
2. Enter the package name (e.g. `com.reddit.frontpage` or `com.google.android.youtube`).
3. AutoMorph automatically checks Google Play and fallback sources (APKCombo, Uptodown, APKPure) to detect valid versions and metadata.

### 2.2 Choosing Patch Repositories
Specify which patch repository to use for the app (e.g., ReVanced, Morphe patches, or custom community repositories). AutoMorph queries the repository releases and discovers compatible patches.

### 2.3 Enabling and Disabling Apps
Each app card features a toggle switch:
* **Enabled (ON)**: Included in daily scheduled patching checks.
* **Disabled (OFF)**: Kept in your configuration but skipped during automated runs.

---

## 3. Customizing Patch Options

For any package, click **Options** / **Customize Patches**:
* View all available patches provided by the selected repository.
* Toggle individual patches ON or OFF (e.g., disable debugging, custom branding, or specific feature tweaks).
* Edit patch option values where supported (e.g., custom package names, user-agent overrides).
* Click **Save Options** to persist your selections.

---

## 4. Triggering Builds

### 4.1 Manual Single or Batch Builds
* **Single App**: Click the **Run** button on an individual app card to trigger patching for just that package.
* **Run All**: Click **Start Build** in the top navigation bar to run through all enabled packages.
* During patching, a slide-out console displays progress output in real time.

### 4.2 Scheduled Automated Builds
AutoMorph includes an internal daily scheduler. It runs automatically once every 24 hours at the time configured in your system settings.

---

## 5. System & Performance Settings

Access the **Settings** tab in the top navigation bar to fine-tune your environment:

### 5.1 Low-Spec Mode (Recommended for Free Tier)
* **What it does**: Optimizes memory allocation and builds packages sequentially with garbage collection between steps.
* **When to enable**: Essential when hosting on an [Oracle Free Tier E2.1.Micro instance](oracle-setup.md) with 1 GB RAM to prevent out-of-memory errors.

### 5.2 Timezone & Schedule Time
* **Schedule Time**: Specify when daily runs should execute (e.g., `03:00` for 3:00 AM).
* **Timezone**: Set your local IANA timezone (e.g., `America/New_York`, `Europe/London`, `Asia/Tokyo`) so schedules match your local time.

### 5.3 Retention & Storage Cleanup
To prevent your storage disk from filling up:
* **Max Original Packages**: Number of downloaded source APKs to keep per app before pruning old versions.
* **Max Patched Packages**: Number of completed patched APKs to retain per app.
* **Max Logs**: Number of historical build log files to keep.

---

## 6. Email Dispatcher & Notifications

AutoMorph can send rich email build reports directly to your inbox whenever patching completes.

1. Ensure `SMTP_USERNAME` and `SMTP_PASSWORD` are defined in your `.env` file (see [Oracle Setup](oracle-setup.md#32-configure-env)).
2. In the web portal, launch the **Email Settings Wizard** under Settings.
3. Configure:
   * **Sender / Recipient Email**: Address to deliver notifications to.
   * **SMTP Host & Port**: (e.g., `smtp.gmail.com` on port `587`).
4. Click **Send Test Email** to verify your configuration.

Each report contains direct download links, checksums, and patch summaries.

---

## 7. Downloading Builds

You can download completed APKs through multiple avenues:
1. **Web Dashboard**: Click the **Download** button directly on any completed app card.
2. **Notification Emails**: Click the branded download button corresponding to your active tunnel ([Pangolin, Tailscale, or Cloudflare](tunnels.md)).
3. **Mounted Volumes**: Built APKs are stored in the `./apps` directory on the host machine.

---

[← Previous: Remote Access & Tunnels Guide](tunnels.md) | [Documentation Hub](README.md)
