# Lowe's Schedule Bot 🛠️

A Dockerized Python bot that scrapes your Lowe's schedule (Kronos) and syncs it to Google Calendar.

## Features
- **Auto-Sync**: Scrapes your schedule and updates Google Calendar.
- **Diff Logic**: Deletes old shifts and adds new ones (prevents duplicates).
- **Resilient**: Retries automatically if the page fails to load.
- **Secure**: Interactive setup helper for Lowe's and Google credentials.
- **Schedule Mode**: Can run once, daily, or on a recurring interval.

## Deployment (Docker)

1.  **Clone the Repo**:
    ```bash
    git clone https://github.com/your-username/lowes-bot.git
    cd lowes-bot
    ```

2.  **Run Setup (First Time)**:
    Run interactively to enter your credentials.
    ```bash
    docker-compose run --rm lowes-bot
    ```
    - Follow the prompts to enter your Lowe's credentials.
    - If you don't have Google Credentials, it will guide you to create them.

3.  **Run in Background**:
    Once configured, let it run forever (if you chose a schedule):
    ```bash
    docker-compose up -d
    ```

## CLI Options

- **Reset**: To clear all saved data and start fresh:
  ```bash
  docker-compose run --rm lowes-bot --reset
  ```

## Development

- **Files**:
  - `lowes_schedule_bot.py`: Main logic.
  - `docker-compose.yml`: Docker orchestration.
  - `data/`: Contains `config.json`, `token.json`, `credentials.json` (Ignored by Git).

## Google API Setup
You need a `credentials.json` file from Google Cloud Console.
1.  Enable "Google Calendar API".
2.  Create "OAuth Client ID" (Desktop App).
3.  Download JSON or paste ID/Secret when prompted by the bot.
