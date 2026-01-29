# Lowe's Schedule Bot 🛠️

A Dockerized Python bot that scrapes your Lowe's schedule (Kronos) and syncs it to Google Calendar.

## Features
- **Auto-Sync**: Scrapes your schedule and updates Google Calendar.
- **Diff Logic**: Deletes old shifts and adds new ones (prevents duplicates).
- **Resilient**: Retries automatically if the page fails to load.
- **Secure**: Interactive setup helper for Lowe's and Google credentials.
- **Schedule Mode**: Can run once, daily, or on a recurring interval.

## Deployment (Docker / Dockge)

### Option 1: Headless / Dockge (Recommended)
You can configure everything via environment variables in your `compose.yaml` without needing to interact with a terminal.

```yaml
services:
  bucket-bot:
    build: https://github.com/Toe-Fur/BucketBot.git#main
    container_name: bucket-bot
    restart: unless-stopped
    volumes:
      - ./data:/app/data
    stdin_open: true
    tty: true
    environment:
      # Lowe's Login
      - LOWES_USERNAME=99999
      - LOWES_PASSWORD=YourPassword!
      - LOWES_PIN=1234
      
      # Discord (Optional)
      - LOWES_DISCORD_WEBHOOK=
      
      # Schedule Settings
      - RUN_MODE=daily     # Options: daily, interval, once
      - RUN_VALUE=08:00    # Time (24h) or Interval (hours)
      
      # Google Credentials (Optional, if you don't have json file yet)
      - GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
      - GOOGLE_CLIENT_SECRET=your-client-secret
      
      # Google Token (REQUIRED for headless server - copy from your PC's token.json)
      - GOOGLE_TOKEN_JSON='{"token": "...", "refresh_token": "...", ...}'
```

### Option 2: Interactive Setup
1.  Clone the repo:
    ```bash
    git clone https://github.com/your-username/lowes-bot.git
    cd lowes-bot
    ```

2.  Run setup:
    ```bash
    docker-compose run --rm lowes-bot
    ```
    - Follow the prompts to enter your Lowe's credentials.
    - If you don't have Google Credentials, it will guide you to create them.

3.  Run in Background:
    ```bash
    docker-compose up -d
    ```

## CLI Options

- **Reset**: To clear all saved data and start fresh:
  ```bash
  docker-compose run --rm lowes-bot --reset
  ```

## Google API Setup
You need a `credentials.json` file from Google Cloud Console.
1.  Enable "Google Calendar API".
2.  Create "OAuth Client ID" (Desktop App).
3.  Use the `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` env vars OR let the bot prompt you.
