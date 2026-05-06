# EventTrace VPS Deployment Guide (Hetzner / DigitalOcean)

This guide explains how to deploy the EventTrace backend on a standard Linux VPS (like Hetzner, DigitalOcean, or Contabo) using `systemd`. 

The frontend remains on **Vercel** and the database remains on **Supabase**. This is a great, robust architecture because:
1. **Supabase (Database):** Fully managed, handles backups, connection pooling (via PgBouncer), and scales easily. You don't have to manage Postgres yourself on the VPS.
2. **Vercel (Frontend):** Perfect for React/Vite, free global CDN, zero-config deploys.
3. **VPS (Backend):** Gives you full control to run your 4 separate background processes (API, monitor, scheduler, bot) cheaply and reliably, with enough RAM for Playwright.

---

## 1. Initial VPS Setup

Buy an **Ubuntu 24.04** (or 22.04) server. Once it is running, SSH into it:
```bash
ssh root@<your_server_ip>
```

Update the system and install required system packages:
```bash
apt update && apt upgrade -y
apt install -y git python3-venv python3-pip curl
```

---

## 2. Clone the Code and Setup Python

We will run the app under a dedicated user (or just use root if you prefer simplicity for this project space, but using a non-root user is safer. For this guide, we'll keep it simple in `/opt`).

```bash
# Clone the repo
cd /opt
git clone https://github.com/ayushhCreator/EventTrace.git
cd EventTrace

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .

# Install Playwright Chromium (required for monitor and causelist scraper)
playwright install chromium --with-deps
```

---

## 3. Configure Environment Variables

Create a `.env` file in the project root containing your Supabase URL and all secrets:

```bash
nano /opt/EventTrace/.env
```

Paste your secrets into it:
```env
# Server Binding
CHD_API_HOST=0.0.0.0
CHD_API_PORT=8009

# Database (Your Supabase connection string)
DATABASE_URL=postgresql://postgres.[YOUR_PROJECT_ID]:[YOUR_PASSWORD]@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres

# Twilio & Auth (Replace with your actual keys!)
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=ed...
TWILIO_WHATSAPP_FROM=whatsapp:+1415...
TELEGRAM_TOKEN=123...
TELEGRAM_BOT_USERNAME=Eventtrace_bot
JWT_SECRET=your_secure_random_string
CORS_ORIGINS=https://event-trace-web.vercel.app/
CHD_CORS_ORIGINS=https://event-trace-web.vercel.app/
```
Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X`).

---

## 4. Create Systemd Services

We need to create service files so Ubuntu automatically starts your 4 processes on boot, and restarts them if they crash.

### A. The API Service (FastAPI)
```bash
nano /etc/systemd/system/eventtrace-api.service
```
Paste:
```ini
[Unit]
Description=EventTrace FastAPI
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/EventTrace
EnvironmentFile=/opt/EventTrace/.env
ExecStart=/opt/EventTrace/.venv/bin/chd-api
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### B. The Monitor Service (Display Board Scraper)
```bash
nano /etc/systemd/system/eventtrace-monitor.service
```
Paste:
```ini
[Unit]
Description=EventTrace Display Monitor
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/EventTrace
EnvironmentFile=/opt/EventTrace/.env
ExecStart=/opt/EventTrace/.venv/bin/chd-run-monitor
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### C. The Scheduler Service (Nightly Causelist Scraper)
*This is the process that was missing on Railway!*
```bash
nano /etc/systemd/system/eventtrace-scheduler.service
```
Paste:
```ini
[Unit]
Description=EventTrace Causelist Scheduler
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/EventTrace
EnvironmentFile=/opt/EventTrace/.env
ExecStart=/opt/EventTrace/.venv/bin/chd-schedule-causelist
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## 5. Start and Enable the Services

Reload `systemd` to recognize the new files, then enable them to start on boot, and finally start them now:

```bash
systemctl daemon-reload

systemctl enable eventtrace-api eventtrace-monitor eventtrace-scheduler
systemctl start eventtrace-api eventtrace-monitor eventtrace-scheduler
```

Check their status to make sure they are running (they should say `active (running)` in green):
```bash
systemctl status eventtrace-api
systemctl status eventtrace-monitor
systemctl status eventtrace-scheduler
```

---

## 6. How to View Logs

Since everything runs via systemd, you use `journalctl` to view the logs for any process.

**View API logs live:**
```bash
journalctl -u eventtrace-api -f
```

**View Monitor logs live:**
```bash
journalctl -u eventtrace-monitor -f
```

**View Scheduler logs live:**
```bash
journalctl -u eventtrace-scheduler -f
```

*(Press `Ctrl+C` to exit the live log view)*

---

## 7. Pointing Vercel to your new Backend

Your API is now running on your server's IP address on port 8009 (e.g., `http://YOUR_SERVER_IP:8009`).

1. Go to your **Vercel** dashboard for `EventTrace-Web`.
2. Go to **Settings** -> **Environment Variables**.
3. Update `VITE_API_URL` to point to your new IP: `http://YOUR_SERVER_IP:8009`.
4. Redeploy the frontend.

*(Note: If Vercel forces HTTPS on the frontend, standard browser security won't allow it to talk to an `http://` IP address. You will eventually need to put a reverse proxy like Nginx or Caddy on your VPS to provide HTTPS using Let's Encrypt, or put the VPS IP behind Cloudflare).*