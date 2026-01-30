# Lowe's Schedule Synchronization Service 🛠️

A professional, Dockerized synchronization service that securely scrapes your Lowe's schedule (Kronos) and maintains an up-to-date calendar in Google Calendar with smart diffing logic.

## Key Enhancements (v3.3.0)
- **Smart Synchronization**: Intelligent diffing mechanism only updates what has changed, reducing API calls and noise.
- **Hardened Configuration**: Protection against accidental credential overwrites in Docker/Dockge.
- **Professional Releases**: Automated GitHub Releases with compiled Windows binaries.
- **Dynamic Timezone Support**: Respects system `TZ` environment variables for accurate local time reporting.

---

## 🏗️ How to "Make a Build"

### 🐳 Option 1: Docker (Recommended)
This is the standard way to run the service. Building the "stack" ensures all dependencies (Chrome, Tesseract, etc.) are version-locked and isolated.

1.  **Open a Terminal** (PowerShell or CMD) in the project directory.
2.  **Run the Build Command**:
    ```powershell
    docker compose build
    ```
3.  **Start the Service**:
    ```powershell
    docker compose up -d
    ```

### 📦 Option 2: Standalone Executable (Windows)
If you want to run the bot as a normal `.exe` file without Docker:

1.  **Install PyInstaller**:
    ```powershell
    pip install pyinstaller
    ```
2.  **Build the Executable**:
    ```powershell
    pyinstaller lowes_schedule_bot.spec
    ```
3.  **Find your Build**: The finished file will be in the `dist/` folder.

### 📦 Option 3: Official GitHub Releases (Easiest for Windows)
For a polished, professional experience:
1.  Navigate to the **"Releases"** section on the right-hand side of this GitHub repository.
2.  Download the latest version's **LoweSyncService.exe**.
3.  Run the `.exe` directly on your Windows machine.

---

## 🐳 Deployment on Linux (Dockge)

The "Lowe's Schedule Synchronization Service" is purpose-built for headless Linux servers running **Dockge**.

### 1. Transfer Credentials
Since the initial Google authorization requires a browser, it is easiest to generate your `token.json` on your Windows PC first and then move it to the server.

1.  Run the bot locally once to successful login.
2.  Copy the contents of your local `data/` folder (specifically `token.json` and `credentials.json`).
3.  In your Linux server's project directory (usually `/opt/stacks/bucket-bot/data`), create those same files.

### 2. Dockge Stack Configuration
Paste the following into your Dockge editor:

```yaml
services:
  bucket-bot:
    build: .
    container_name: bucket-bot
    restart: unless-stopped
    volumes:
      - ./data:/app/data
    environment:
      - LOWES_USERNAME=1234567  # Your Lowe's Sales ID
      - LOWES_PASSWORD=Password # Your Lowe's Password
      - LOWES_PIN=1111        # Your 4-Digit PIN
      - RUN_MODE=daily        # "once", "daily", or "interval"
      - RUN_VALUE=08:00       # Time (24h) or Hours Interval
      - TZ=America/New_York   # Set your local timezone
    stdin_open: true
    tty: true
```

### 3. Deploy
Click **"Deploy"** in Dockge. The service will build, initialize its headless environment, and begin the synchronization schedule.

---

## 🛠️ Maintenance Commands

### Monitor Logs
```powershell
docker compose logs -f bucket-bot
```

### Force an Immediate Synchronization
```powershell
docker exec bucket-bot python lowes_schedule_bot.py --once
```

### Reset System State
```powershell
docker compose run --rm bucket-bot --reset
```
