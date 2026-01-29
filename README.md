# Lowe's Schedule Bot 🛠️

A Dockerized Python bot that scrapes your Lowe's schedule (Kronos) and syncs it to Google Calendar.

## Features
- **Auto-Sync**: Scrapes your schedule and updates Google Calendar.
- **Diff Logic**: Deletes old shifts and adds new ones (prevents duplicates).
- **Resilient**: Retries automatically if the page fails to load.
- **Secure**: Interactive setup helper for Lowe's and Google credentials.
- **Schedule Mode**: Can run once, daily, or on a recurring interval.

## Deployment (Docker / Dockge)

### 🚀 Recommended Setup (Headless Server)
The most reliable way to set up the bot on a remote server (like Dockge/Portainer) is to upload your credentials via SFTP.

1.  **Prepare Files on your PC**: Run the bot once locally to generate `data/credentials.json` and `data/token.json`.
2.  **Upload via SFTP**: 
    - Create the folder `/opt/stacks/bucket-bot/data/` on your server.
    - Upload your `token.json` and `credentials.json` into that `data` folder.
3.  **Fix Permissions**: Run this on your server terminal so Docker can read the files:
    ```bash
    sudo chown -R $USER: /opt/stacks/bucket-bot
    sudo chmod -R 775 /opt/stacks/bucket-bot
    ```
4.  **Dockge / Compose Config**:
    ```yaml
    services:
      bucket-bot:
        build: https://github.com/Toe-Fur/BucketBot.git#main
        container_name: bucket-bot
        restart: unless-stopped
        volumes:
          - ./data:/app/data
        environment:
          - LOWES_USERNAME=5001234
          - LOWES_PASSWORD=YourPassword!
          - LOWES_PIN=1234
          - RUN_MODE=daily
          - RUN_VALUE=08:00
          # - LOWES_DISCORD_WEBHOOK="https://discord.com/api/webhooks/..."
    ```

### 🛠️ Alternative: Environment Variables
If you don't want to use SFTP, you can inject everything via `compose.yaml`. **Note**: This can be tricky with JSON quoting.

```yaml
      - GOOGLE_CLIENT_ID="your-id.apps.googleusercontent.com"
      - GOOGLE_CLIENT_SECRET="your-secret"
      - GOOGLE_TOKEN_JSON='{"token": "ya29...", "refresh_token": "...", ...}'
```

## CLI Commands

### Force an Immediate Run
In your server terminal:
```bash
docker exec bucket-bot python lowes_schedule_bot.py --once
```

### Reset All Data
```bash
docker compose run --rm bucket-bot --reset
```
