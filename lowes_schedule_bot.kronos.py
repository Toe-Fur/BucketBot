from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image
import pytesseract
import time
from ics import Calendar, Event
from datetime import datetime, timedelta
import re
from bs4 import BeautifulSoup
from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import sys
import os
from google_calendar_diff_utils import build_diff_notifications

chrome_options = Options()
chrome_options.add_argument("--headless=new")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--window-size=1920,1080")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument(
    "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
)

driver = webdriver.Chrome(options=chrome_options)

SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_calendar_service():
    creds = None
    BASE_DIR = getattr(sys, '_MEIPASS', os.path.abspath("."))
    TOKEN_PATH = os.path.join(BASE_DIR, 'token.json')
    CREDENTIALS_PATH = os.path.join(BASE_DIR, 'credentials.json')

    # Load existing token if present
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # Handle missing/expired token
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                print("⚠️ Token expired or revoked. Re-authentication required.")
                os.remove(TOKEN_PATH)
                creds = None  # Trigger full re-auth
        if not creds or not creds.valid:
            print("🔑 Opening browser for reauthorization...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
            with open(TOKEN_PATH, 'w') as token_file:
                token_file.write(creds.to_json())

    return build('calendar', 'v3', credentials=creds)

# For timestamped filenames
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# ---- CONFIG ----
USERNAME = '5001182'
PASSWORD = 'lowesEiho8sho1P!@1'
PIN = '4299'
TESSERACT_PATH = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

# ---- LOGIN TO MYLOWESLIFE ----
driver.get('https://www.myloweslife.com')
WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "idToken2")))
driver.find_element(By.ID, 'idToken1').send_keys(USERNAME)
driver.find_element(By.ID, 'idToken2').send_keys(PASSWORD)
driver.find_element(By.ID, 'loginButton_0').click()
WebDriverWait(driver, 30).until(EC.invisibility_of_element((By.ID, "idToken2")))
WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "idToken1")))
driver.find_element(By.ID, 'idToken1').send_keys(PIN)
driver.find_element(By.ID, 'loginButton_0').click()

# ---- CLICK KRONOS TILE ----
WebDriverWait(driver, 30).until(EC.presence_of_all_elements_located((By.CLASS_NAME, "toolname")))

# Robust scroll loop
scroll_pause_time = 1
last_height = driver.execute_script("return document.body.scrollHeight")
for _ in range(5):
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(scroll_pause_time)
    new_height = driver.execute_script("return document.body.scrollHeight")
    if new_height == last_height:
        break
    last_height = new_height

time.sleep(2)
tiles = driver.find_elements(By.CLASS_NAME, "toolname")
for tile in tiles:
    if "Kronos" in tile.text:
        tile.click()
        break

# ---- CLICK STORES ----
time.sleep(2)
stores_links = driver.find_elements(By.PARTIAL_LINK_TEXT, "Stores")
for link in stores_links:
    if link.is_displayed():
        link.click()
        break

# ---- SECOND LOGIN ----
time.sleep(5)
driver.switch_to.window(driver.window_handles[-1])
WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "idToken2")))
driver.find_element(By.ID, 'idToken1').send_keys(USERNAME)
driver.find_element(By.ID, 'idToken2').send_keys(PASSWORD)
driver.find_element(By.ID, 'loginButton_0').click()
WebDriverWait(driver, 30).until(EC.invisibility_of_element((By.ID, "idToken2")))
WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "idToken1")))
driver.find_element(By.ID, 'idToken1').send_keys(PIN)
driver.find_element(By.ID, 'loginButton_0').click()

# ---- ACKNOWLEDGE IF NEEDED ----
try:
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "idToken2_0")))
    driver.find_element(By.ID, "idToken2_0").click()
except:
    pass

# ---- SCHEDULE PAGE ----
print("Waiting for schedule to fully render...")
time.sleep(20)  # Let everything load visually

timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
screenshot_path = f"schedule_{timestamp}.png"

driver.save_screenshot(f"schedule_{timestamp}.png")
print(f"Saved full-page screenshot as {screenshot_path}")

# driver.quit()

from bs4 import BeautifulSoup

# ---- PARSE HTML FOR SCHEDULE ----
calendar = Calendar()

# Use BeautifulSoup to parse the most recent saved HTML (use this if testing offline)
# with open("raw_schedule_dump.html", "r", encoding="utf-8") as file:
#     soup = BeautifulSoup(file, "html.parser")

# --- Switch to dynamic iframe ---
iframe = WebDriverWait(driver, 15).until(
    EC.presence_of_element_located((By.XPATH, "//iframe[starts-with(@id, 'widgetFrame')]"))
)
driver.switch_to.frame(iframe)

# THEN parse the inner page
soup = BeautifulSoup(driver.page_source, 'html.parser')

# Extract all date cells with a shift
date_cells = soup.find_all('td', attrs={"title": re.compile(r"\d{1,2}/\d{1,2}/\d{4}")})
print(f"Found {len(date_cells)} potential shift cells.")
# --- SWITCH TO SCHEDULE IFRAME AND PARSE ---

date_cells = soup.find_all('td', attrs={"title": re.compile(r"\d{1,2}/\d{1,2}/\d{4}")})
print(f"Found {len(date_cells)} potential shift cells.")

for cell in date_cells:
    date_str = cell.get("title")
    if not date_str:
        continue
    try:
        date = datetime.strptime(date_str, "%m/%d/%Y")
    except:
        continue

    shift_div = cell.find("div", class_="caldayItem1")
    if not shift_div:
        print(f"❌ No shift found for {date_str}")
        continue

    shift_text = shift_div.get_text(strip=True)
    match = re.search(r'(\d{1,2})(?::?(\d{2}))?([ap])m?\s*-\s*(\d{1,2})(?::?(\d{2}))?([ap])m?', shift_text.lower())
    if not match:
        print(f"❌ Unrecognized shift format on {date_str}: '{shift_text}'")
        continue

    # Convert 'a'/'p' to 'AM'/'PM'
    sh, sm, sap, eh, em, eap = match.groups()
    sm = sm or "00"
    em = em or "00"

    start_time = datetime.strptime(f"{sh}:{sm}{sap}m", "%I:%M%p").time()
    end_time = datetime.strptime(f"{eh}:{em}{eap}m", "%I:%M%p").time()

    start_dt = datetime.combine(date.date(), start_time)
    end_dt = datetime.combine(date.date(), end_time)

    event = Event()
    event.name = "Lowe's 🛠️"
    event.begin = start_dt
    event.end = end_dt
    calendar.events.add(event)

    print(f"✔️ Shift added: {date_str} → {start_time.strftime('%I:%M %p')} - {end_time.strftime('%I:%M %p')}")

    import requests

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1405687597728268499/UmoVEnYYScVMcy80t55sTJYOXFeDiXYv0PJ_vILrUNEtR2PmG6WgqphoI_NMvBLG2opg"

def send_discord_update(changes):
    if not changes:
        return
    lines = ["📅 **Schedule Update:**"]
    for change in changes:
        lines.append(change)
    msg = "\n".join(lines)
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
        print("📨 Sent Discord notification.")
    except Exception as e:
        print(f"❌ Failed to send Discord notification: {e}")

def sync_to_google_calendar(calendar, calendar_id='primary'):
    service = get_calendar_service()
    updates = []

    # Define time range: 30 days in past to 30 days in future
    now = datetime.utcnow()
    time_min = (now - timedelta(days=30)).isoformat() + 'Z'
    time_max = (now + timedelta(days=30)).isoformat() + 'Z'

    # Step 1: Get all Lowe's events within the 60-day window
    all_events = service.events().list(
        calendarId=calendar_id,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy='startTime'
    ).execute().get('items', [])

    lowes_events = [e for e in all_events if e.get('summary') == "Lowe's 🛠️"]
    deleted_dates = set()

    # Step 2: Delete all Lowe's 🛠️ events in the range
    for event in lowes_events:
        start = event['start'].get('dateTime')
        if not start:
            continue
        date_key = start[:10]
        try:
            service.events().delete(calendarId=calendar_id, eventId=event['id']).execute()
            deleted_dates.add(date_key)
            print(f"🗑️ Deleted old shift on {date_key} {start[11:]}")
        except Exception as e:
            print(f"❌ Failed to delete: {e}")

    # Step 3: Add new events (parsed from calendar)
    added_dates = set()
    for event in calendar.events:
        date_key = event.begin.format('YYYY-MM-DD')
        start = event.begin.format('YYYY-MM-DDTHH:mm:ss')
        end = event.end.format('YYYY-MM-DDTHH:mm:ss')

        try:
            service.events().insert(calendarId=calendar_id, body={
                'summary': event.name,
                'start': {'dateTime': start, 'timeZone': 'America/Los_Angeles'},
                'end': {'dateTime': end, 'timeZone': 'America/Los_Angeles'}
            }).execute()
            added_dates.add(date_key)
            print(f"✅ Added shift on {date_key} {start[11:]}–{end[11:]}")
        except Exception as e:
            print(f"❌ Failed to add event: {e}")

    # Step 4: Notify of only updated days
    changed_dates = sorted(added_dates.union(deleted_dates))
    if changed_dates:
        lines = ["📅 **Schedule Changes:**"]
        for date in changed_dates:
            if date in deleted_dates and date in added_dates:
                lines.append(f"🔁 Updated shift on {date}")
            elif date in deleted_dates:
                lines.append(f"❌ Removed shift on {date}")
            elif date in added_dates:
                lines.append(f"➕ New shift on {date}")
        send_discord_update(lines)
    else:
        print("✅ No calendar changes; no Discord notification.")

# Save calendar file
print(f"✅ {len(calendar.events)} shift(s) added.")

ics_path = f"schedule_{timestamp}.ics"
with open(ics_path, 'w', encoding='utf-8') as f:
    f.write(str(calendar))

print(f"Calendar saved as {ics_path}")

driver.quit()

sync_to_google_calendar(calendar)
