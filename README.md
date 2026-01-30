```text
     __                                 _____                    
    / /   ____ _      _____  _____     / ___/ __  ______  _____  
   / /   / __ \ | /| / / _ \/ ___/     \__ \ / / / / __ \/ ___/  
  / /___/ /_/ / |/ |/ /  __(__  )     ___/ // /_/ / / / / /__    
 /_____/\____/|__/|__/\___/____/     /____/ \__, /_/ /_/\___/    
                                           /____/                
```

# LoweSync: Schedule Synchronization Service

A robust, enterprise-grade synchronization service designed to securely bridge Lowe's UKG schedules with Google Calendar. This service features intelligent diffing logic, session-hardened authentication, and native Docker support for reliable long-term operation.

## Key Features (v3.4.7)

*   **Intelligent Synchronization**: Advanced diffing mechanism ensures only schedule changes are propagated to the calendar.
*   **Robust TZ Validation**: Automatic correction and warnings for timezone typos to prevent silent scraping failures.
*   **Fail-Safe Parsing**: A brute-force fallback engine that captures shifts even when standard page elements load slowly or unclearly.
*   **Deep Crawl**: An optimized 3-page search strategy (Current + 2 months) that combines Grid and Aside views for comprehensive coverage.
*   **Safe Start**: Prevent blocking on optional configuration fields in Docker/non-interactive environments.
*   **Automated Log Retention**: Screenshots, HTML snapshots, and ICS files are automatically purged after a configurable period (default 7 days).
*   **Professional Deployment**: Automated GitHub Releases providing pre-built Windows binaries and optimized Docker images.
*   **Timezone Resilience**: Native support for the `TZ` environment variable ensures temporal accuracy across global regions.

---

## Google Calendar API Setup

Initial setup requires a "Desktop App" credential from the Google Cloud Console.

1.  **Create Project**: Go to the [Google Cloud Console](https://console.cloud.google.com/) and create a new project (e.g., "LoweSync").
2.  **Enable API**: 
    - Navigate to **APIs & Services** > **Library**.
    - Search for **"Google Calendar API"** and click **Enable**.
3.  **Configure Auth Platform (Consent Screen)**:
    - Click **"Branding"** in the left sidebar.
    - Fill in the **App Name** (e.g., "LoweSync") and **Support Email**.
    - Scroll down and click **Save and Continue**.
    - Click **"Audience"** in the left sidebar.
    - Choose **User Type: External**.
    - Under **"Test users"**, click **"+ ADD USERS"**.
    - Type your **own Gmail address**, click **ADD**, then click **Save**.
4.  **Create Credentials (client_secret)**:
    - Click **"Clients"** in the left sidebar.
    - Click **+ Create Client** > **OAuth client ID**.
    - Select **Application type: Desktop app**.
    - Name it "LoweSync Bot" and click **Create**.
5.  **Download Key**:
    - Locate your new OAuth Client ID in the list.
    - Click the **Download JSON** icon (⬇️) on the far right.
    - Rename the downloaded file to `credentials.json` and place it in the project root.

---

## Execution and Deployment

### Option 1: Docker
Recommended for server deployment and long-term stability.

1.  **Build Phase**:
    ```bash
    docker compose build
    ```
2.  **Deployment Phase**:
    ```bash
    docker compose up -d
    ```

### Option 2: Standalone Binary (Windows)
Optimized for local execution without external dependencies.

1.  **Provision Dependencies**:
    ```powershell
    pip install pyinstaller -r requirements.txt
    ```
2.  **Compilation**:
    ```powershell
    pyinstaller lowes_schedule_bot.spec
    ```
3.  **Distribution**: The compiled executable is located within the `dist/` directory.

### Option 3: Official GitHub Releases
For immediate deployment in production environments:
1.  Navigate to the **Releases** section of this repository.
2.  Download the latest stable **LoweSyncService.exe**.

---

## Server Configuration (Linux/Dockge)

LoweSync is optimized for headless Linux environments.

### 1. Security Token Management
Initial Google authorization requires a browser session. It is recommended to authorize locally and transfer the artifacts to the server.

1.  Perform a successful local synchronization to generate `data/token.json`.
2.  Transfer the `data/` directory contents to the server (e.g., `/opt/stacks/bucket-bot/data`).

### 2. Dockge Stack Specification
```yaml
services:
  bucket-bot:
    build: .
    container_name: bucket-bot
    restart: unless-stopped
    volumes:
      - ./data:/app/data
    environment:
      - LOWES_USERNAME=1234567  # Employee Sales ID
      - LOWES_PASSWORD=Password
      - LOWES_PIN=1111 
      - RUN_MODE=daily        # Options: "once", "daily", "interval"
      - RUN_VALUE=08:00       # 24h Time or Hourly Interval
      - LOG_RETENTION_DAYS=7  # Automatically purge artifacts after X days
      - TZ=America/New_York
    stdin_open: true
    tty: true
```

---

## System Administration

### Log Monitoring
```bash
docker compose logs -f bucket-bot
```

### Manual Trigger
```bash
docker exec bucket-bot python lowes_schedule_bot.py --once
```

### State Reset
```bash
docker compose run --rm bucket-bot --reset
```
