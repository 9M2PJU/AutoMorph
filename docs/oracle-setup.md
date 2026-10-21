[🏠 Documentation Hub](README.md) › **Oracle Cloud Free Tier Setup**

---

# Setting Up Oracle Free Tier VPS & Launching AutoMorph

This guide walks you through creating and launching your own free Virtual Private Server (VPS) on Oracle Cloud Infrastructure (OCI) under their **Always Free** tier, configuring SSH access, and starting AutoMorph.

> [!NOTE]
> Oracle occasionally updates their terms and tier policies. As long as you stay on the pure Always Free tier and do not convert to Pay-As-You-Go, you will not be charged. You will need a credit or debit card to register; Oracle charges a temporary verification hold (~$1.00 USD) that is promptly returned to verify account legitimacy.

---

## Table of Contents

- [Step 1: Create a New Instance](#step-1-create-a-new-instance)
  - [1.1 Open Instance Creation](#11-open-instance-creation)
  - [1.2 Basic Instance Settings & Shape](#12-basic-instance-settings--shape)
  - [1.3 Networking](#13-networking)
  - [1.4 Storage & Boot Volume](#14-storage--boot-volume)
  - [1.5 Review & Launch](#15-review--launch)
- [Step 2: Entering the Server (SSH)](#step-2-entering-the-server-ssh)
  - [2.1 SSH via Windows PowerShell](#21-ssh-via-windows-powershell)
  - [2.2 Windows SSH Key Permission Fix (If Needed)](#22-windows-ssh-key-permission-fix-if-needed)
  - [2.3 SSH via macOS / Linux](#23-ssh-via-macos--linux)
- [Step 3: Starting AutoMorph](#step-3-starting-automorph)
  - [3.1 Enter the Project Folder](#31-enter-the-project-folder)
  - [3.2 Configure `.env`](#32-configure-env)
  - [3.3 Starting the Service](#33-starting-the-service)
  - [3.4 Access the Web Portal](#34-access-the-web-portal)
- [Troubleshooting & FAQs](#troubleshooting--faqs)

---

## Step 1: Create a New Instance

### 1.1 Open Instance Creation
1. Log into your [Oracle Cloud Console](https://cloud.oracle.com/).
2. Click the hamburger menu icon (☰) in the top-left corner and navigate to:
   ```text
   Compute > Instances > Create Instance
   ```

<!-- Screenshot placeholder: Oracle menu showing Compute > Instances -->

---

### 1.2 Basic Instance Settings & Shape

* **Name**: Give your instance a memorable name (e.g., `AutoMorph`).
* **Compartment and Placement**: Leave these at their default settings.
* **Image**:
  * Click **Change image**.
  * Select **Canonical Ubuntu** > **Canonical Ubuntu 24.04 Minimal** (or Ubuntu 22.04 Minimal).
  
<!-- Screenshot placeholder: Selecting Ubuntu Minimal -->

* **Shape**:
  * Make sure the shape selected is **VM.Standard.E2.1.Micro** with the **Always Free-eligible** badge.
  * If it defaults to something else, click **Change shape**, select **Specialty and legacy**, and pick **VM.Standard.E2.1.Micro**.

<!-- Screenshot placeholder: Shape selection VM.Standard.E2.1.Micro -->

#### Automated Setup (Initialization Script):
To automatically install Docker, set up a 4GB swapfile, optimize networking MTU, and download the AutoMorph templates:
1. Scroll down and expand **Advanced Options**.
2. Click the **Management** tab.
3. Under **Cloud-init script**, choose **Upload cloud-init script**.
4. Select the [`oracle-cloud-init.yaml`](../oracle-cloud-init.yaml) file from this repository.

<!-- Screenshot placeholder: Uploading the initialization script in Management tab -->

> [!TIP]
> Using `oracle-cloud-init.yaml` automates Docker installation, kernel BBR tuning, MTU configuration, and sets up 4GB of swap space to ensure smooth patching performance on the 1GB RAM micro instance.

---

### 1.3 Networking

Under the **Networking** section:
* **Primary network**: Keep **Create new virtual cloud network** and **Create new public subnet** selected.
* **Assign a public IPv4 address**: Ensure this is checked (**Yes**). If you do not assign a public IP, you will not be able to connect over the internet.
* **SSH Keys**:
  * Choose **Generate a key pair for me**.
  * Download **both** your private key (`.key`) and public key (`.pub`).
  
> [!CAUTION]
> Store your downloaded `.key` file in a secure location. You cannot redownload this key after leaving this page!

<!-- Screenshot placeholder: Downloading SSH keys -->

---

### 1.4 Storage & Boot Volume

Oracle Free Tier accounts allow up to **200 GB** of total boot/block storage across all instances.

* By default, the boot volume is 50 GB, which is plenty for AutoMorph.
* If you want to allocate more space now, check **Specify a custom boot volume size and performance** and enter your desired size (e.g. 100 GB to 200 GB).

<!-- Screenshot placeholder: Custom boot volume size setting -->

---

### 1.5 Review & Launch

1. Review your settings and click **Create**.
2. The instance status will show **PROVISIONING** (orange) and switch to **RUNNING** (green) within a minute or two.
3. Note down the **Public IP Address** displayed on the instance details page.

> [!NOTE]
> If you provided the initialization script (`oracle-cloud-init.yaml`), allow an additional **3 to 5 minutes** after the instance turns green so background package updates and Docker installation can finish.

---

## Step 2: Entering the Server (SSH)

### 2.1 SSH via Windows PowerShell

Open Windows PowerShell and use the standard OpenSSH command:

```powershell
ssh -i <PATH-TO-KEY> ubuntu@<PUBLIC-IP>
```

**Parameters**:
* `<PATH-TO-KEY>`: Shift + Right-click your downloaded `.key` file in File Explorer and select **Copy as path**.
* `ubuntu`: The default username for Ubuntu instances in Oracle Cloud.
* `<PUBLIC-IP>`: The public IP address from your instance dashboard.

**Example**:
```powershell
ssh -i "C:\Users\YourName\Downloads\ssh-key.key" ubuntu@129.150.45.12
```
When prompted `Are you sure you want to continue connecting (yes/no/[fingerprint])?`, type `yes` and hit **Enter**.

---

### 2.2 Windows SSH Key Permission Fix (If Needed)

If Windows PowerShell displays an error like:
```text
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@         WARNING: UNPROTECTED PRIVATE KEY FILE!          @
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
Permissions for 'ssh-key.key' are too open.
```

Fix the file permissions directly in PowerShell by running:
```powershell
# Replace with the actual path to your key
$KeyPath = "C:\Users\YourName\Downloads\ssh-key.key"

icacls $KeyPath /inheritance:r
icacls $KeyPath /grant:r "$($env:USERNAME):(R)"
```

---

### 2.3 SSH via macOS / Linux

On macOS or Linux, restrict the key permissions before connecting:
```bash
chmod 600 /path/to/ssh-key.key
ssh -i /path/to/ssh-key.key ubuntu@<PUBLIC-IP>
```

---

## Step 3: Starting AutoMorph

### 3.1 Enter the Project Folder

If you used the initialization script, the directory is already created with the required templates:
```bash
cd automorph
```

*(If you did not use the initialization script, install Docker & Docker Compose first, then run `mkdir automorph && cd automorph` and download `default_compose.yaml` as `compose.yaml` and `example.env` as `.env`).*

You can verify whether the initialization script has completed by running:
```bash
tail -f /var/log/cloud-init-output.log
```
*(Press `Ctrl + C` once you see completion).*

---

### 3.2 Configure `.env`

Edit the `.env` file to set up email reporting, downloads, and remote access tunnels:
```bash
nano .env
```

Key configuration areas:
1. **Email Reports**: Enter your `SMTP_USERNAME` and `SMTP_PASSWORD` (for Gmail, generate a 16-character [Google App Password](https://myaccount.google.com/apppasswords)).
2. **Tunnel & Remote Access**: Set your preferred tunnel provider (see the [Remote Access & Tunnels Guide](tunnels.md) for details):
   * **Pangolin**: Free public URL with no custom domain required.
   * **Tailscale Funnel**: Secure mesh network or public Funnel link.
   * **Cloudflare Tunnel**: Best if you already have your own domain name.
3. **Set Compose Profile**: If using Pangolin or Cloudflare, ensure you set:
   ```bash
   COMPOSE_PROFILES=pangolin
   # or COMPOSE_PROFILES=cloudflare
   ```

To save and exit in `nano`:
* Press `Ctrl + O`, then `Enter` to save.
* Press `Ctrl + X` to exit.

Verify your saved values:
```bash
cat .env
```

---

### 3.3 Starting the Service

1. Pull the latest AutoMorph image:
   ```bash
   docker compose pull
   ```
2. Start the application in the background:
   ```bash
   docker compose up -d
   ```
3. Check container status:
   ```bash
   docker compose ps
   ```

<!-- Screenshot placeholder: docker compose up -d output -->

---

### 3.4 Access the Web Portal

Once the containers are running:
* If you set up **Pangolin** or **Cloudflare**, navigate to your configured tunnel URL in your browser.
* If you set up **Tailscale**, navigate to your MagicDNS name or Funnel URL.

Congratulations! Your AutoMorph instance is running on Oracle's free tier.

---

## Troubleshooting & FAQs

<details>
<summary><b>Why can't I access http://&lt;PUBLIC-IP&gt;:8080 directly in my browser?</b></summary>

Oracle Cloud Virtual Cloud Networks (VCNs) and Ubuntu's default firewall block ingress traffic on arbitrary ports like 8080 by default. Rather than exposing raw ports over plain HTTP, we strongly recommend using a tunnel (Pangolin, Tailscale, or Cloudflare). Tunnels provide free SSL encryption and require no open ports on the server.
</details>

<details>
<summary><b>How do I check live container logs?</b></summary>

To inspect logs:
```bash
# AutoMorph main application logs
docker compose logs -f automorph

# Pangolin tunnel logs
docker compose logs -f pangolin

# Cloudflare tunnel logs
docker compose logs -f cloudflared
```
</details>

<details>
<summary><b>Will my Oracle instance stay free forever?</b></summary>

Yes, as long as your shape is `VM.Standard.E2.1.Micro` (or Ampere A1 within limits) and total boot volume across all your instances remains ≤ 200 GB, it remains within Oracle's Always Free tier.
</details>

---

[← Documentation Hub](README.md) | [Next: Remote Access & Tunnels Guide →](tunnels.md)
