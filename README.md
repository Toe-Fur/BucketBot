# Lowe's Schedule Synchronization Service 🛠️

A professional, Dockerized synchronization service that securely scrapes your Lowe's schedule (Kronos) and maintains an up-to-date calendar in Google Calendar with smart diffing logic.

## Key Enhancements (v3.1.0)
- **Smart Synchronization**: Intelligent diffing mechanism only updates what has changed, reducing API calls and noise.
- **Session Persistence**: Authentication is handled per-task, ensuring the service remains logged in during long-term operation.
- **Professional Logging**: Formalized system output for clear monitoring and audits.
- **Dynamic Timezone Support**: Respects system `TZ` environment variables for accurate local time reporting.

---

## 🏗️ How to "Make a Build"

### 🐳 Option 1: Docker (Recommended)
This is the standard way to run the service. Building the "stack" ensures all dependencies (Chrome, Tesseract, etc.) are version-locked and isolated.

1.  **Open a Terminal** (PowerShell or CMD) in the project directory.
2.  **Run the Build Command**:
    ```powershell
    docker-compose build
    ```
3.  **Start the Service**:
    ```powershell
    docker-compose up -d
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

---

## 🚀 Deployment (Docker / Dockge)

The most reliable way to set up the service on a remote server is using the provided `docker-compose.yml`.

1.  **Initialize locally**: Run the service once to generate your `data/token.json`.
2.  **Deploy**:
    ```yaml
    services:
      bucket-bot:
        build: .
        container_name: bucket-bot
        restart: unless-stopped
        volumes:
          - ./data:/app/data
        environment:
          - LOWES_USERNAME=YourSalesID
          - LOWES_PASSWORD=YourPassword
          - LOWES_PIN=1234
          - RUN_MODE=daily
          - RUN_VALUE=08:00
          - TZ=America/New_York
    ```

## 🛠️ Maintenance Commands

### Monitor Logs
```powershell
docker-compose logs -f bucket-bot
```

### Force an Immediate Synchronization
```powershell
docker exec bucket-bot python lowes_schedule_bot.py --once
```

### Reset System State
```powershell
docker-compose run --rm bucket-bot --reset
```
