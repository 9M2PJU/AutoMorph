# AutoMorph Documentation Hub

Welcome to the **AutoMorph** documentation! Here you will find step-by-step guides for hosting, configuring, exposing, and using AutoMorph.

---

## 📚 Guides & Documentation

Choose a guide below to get started:

### ☁️ [1. Oracle Cloud Free Tier Setup](oracle-setup.md)
* Learn how to set up an **Always Free** VPS on Oracle Cloud Infrastructure (OCI).
* Step-by-step guide through instance creation, shape selection (`VM.Standard.E2.1.Micro`), and automated setup via cloud-init.
* Connecting via Windows PowerShell (with SSH key permission fixes) and starting Docker.

### 🚇 [2. Remote Access & Tunnels Guide](tunnels.md)
* Expose your AutoMorph web portal securely over HTTPS with zero port-forwarding:
  * **🔴 Pangolin**: Quickest setup, free public URL, zero custom domain required.
  * **🔵 Tailscale Funnel**: Secure mesh network access or public HTTPS endpoint.
  * **🟠 Cloudflare Tunnels**: Best choice if you own a custom domain.
* Instructions on setting compose profiles and viewing tunnel logs.

### 📖 [3. User Guide & Web Interface](user-guide.md)
* Comprehensive tour of the web portal:
  * Adding and configuring packages.
  * Customizing patch options and repositories.
  * Triggering builds and configuring automated daily schedules.
  * Enabling **Low-Spec Mode** for 1GB RAM instances.
  * Setting up automated email build notifications and downloading APKs.

---

## 🗺️ Recommended Setup Flow

```mermaid
graph TD
    A[1. Launch Server<br/>Oracle Free Tier VPS] -->|oracle-cloud-init.yaml| B[2. Configure .env<br/>Email & Credentials]
    B --> C[3. Choose a Tunnel<br/>Pangolin, Tailscale, or Cloudflare]
    C --> D[4. docker compose up -d<br/>Service Running]
    D --> E[5. Open Web Portal<br/>Add Packages & Customise Patches]
    E --> F[6. Enjoy Automated Daily Builds<br/>& Email Download Links]
```

---

## ⚙️ Key Configuration Files

* [`default_compose.yaml`](../default_compose.yaml): Baseline Docker Compose specification with built-in profiles for Cloudflare and Pangolin.
* [`example.env`](../example.env): Environment template for SMTP credentials, Google Play authentication, and tunnel tokens.
* [`oracle-cloud-init.yaml`](../oracle-cloud-init.yaml): Cloud-init provisioning script for Oracle instances (swaps, Docker, MTU clamping, and templates).

---

## 💡 Quick Tips

* **Low RAM Instances**: Always enable **Low-Spec Mode** in the Web Portal under *Settings* when hosting on a 1GB RAM instance.
* **Inspect Logs**: Run `docker compose logs -f automorph` from your project folder to observe active builds and server events.

---

[← Back to Main Repository](../README.md)
