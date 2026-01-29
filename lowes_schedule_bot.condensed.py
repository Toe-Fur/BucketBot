# minimal_ukg_sync.py — condensed, "only print important stuff"

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bs4 import BeautifulSoup
from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from ics import Calendar, Event
from datetime import datetime, timedelta
from types import SimpleNamespace
import re, time, os, sys, requests

# ===== Config (use env vars!) =====
USERNAME = os.getenv("LOWES_USER")
PASSWORD = os.getenv("LOWES_PASS")
PIN      = os.getenv("LOWES_PIN")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")  # optional
SCOPES = ['https://www.googleapis.com/auth/calendar']
TZ = 'America/Los_Angeles'
T = SimpleNamespace(short=1.0, med=4.0)
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# ===== Regex helpers =====
MONTHS = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"sept":9,"oct":10,"nov":11,"dec":12}
MONTH_YEAR_RX = re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{4})", re.I)
TIME_RANGE_RX = re.compile(r"(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?|am|pm|a|p))\s*[-–—]\s*(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?|am|pm|a|p))", re.I)

# ===== Selenium =====
def driver_new():
    opts = Options()
    # opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    return webdriver.Chrome(options=opts)

def wait_for_any(driver, locators, timeout):
    end = time.time() + timeout
    while time.time() < end:
        for by, sel in locators:
            try:
                return WebDriverWait(driver, 0.6).until(EC.presence_of_element_located((by, sel)))
            except: pass
        time.sleep(0.1)
    raise TimeoutError("wait_for_any timed out")

def on_schedule_page_strict(driver):
    try:
        wait_for_any(driver, [
            (By.XPATH, "//*[contains(normalize-space(.),'Previous') and contains(normalize-space(.),'Next')]"),
            (By.XPATH, "//*[@role='navigation'][.//*[contains(.,'Previous')] and .//*[contains(.,'Next')]]"),
        ], T.med)
        wait_for_any(driver, [
            (By.XPATH, "//*[@role='grid' or @role='table']//*[self::tr or .//th[contains(.,'Sun') or contains(.,'Mon') or contains(.,'Tue') or contains(.,'Wed') or contains(.,'Thu') or contains(.,'Fri') or contains(.,'Sat')]]")
        ], T.med)
        return True
    except: return False

def click_view_my_schedule_link(driver):
    for by, sel in [
        (By.XPATH, "//a[normalize-space()='View My Schedule']"),
        (By.XPATH, "//button[normalize-space()='View My Schedule']"),
        (By.XPATH, "//*[self::a or self::button][contains(translate(normalize-space(.),'VIEW MY SCHEDULE','view my schedule'),'view my schedule')]"),
        (By.XPATH, "//*[contains(@data-action,'view-schedule')]"),
    ]:
        try:
            el = WebDriverWait(driver, T.short).until(EC.element_to_be_clickable((by, sel)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            driver.execute_script("arguments[0].click();", el); return True
        except: pass
    return False

def get_period_label(driver):
    for by, sel in [
        (By.XPATH, "//*[contains(.,'Previous') and contains(.,'Next')]/following::*[@role='heading' or self::h1 or self::h2 or self::h3][1]"),
        (By.XPATH, "//h1|//h2|//h3"),
        (By.XPATH, "(//*[@role='grid' or self::table])[1]"),
    ]:
        try:
            txt = driver.find_element(by, sel).text.strip()
            if txt: return txt[:120]
        except: pass
    return str(time.time())

def click_next_and_wait_change(driver):
    before = get_period_label(driver)
    for by, sel in [
        (By.XPATH, "((//*[contains(normalize-space(.),'Previous') and contains(normalize-space(.),'Next')])[1]//*[self::button or self::a][normalize-space()='Next'])[1]"),
        (By.XPATH, "((//*[contains(normalize-space(.),'Previous') and contains(normalize-space(.),'Next')])[1]//*[self::button or self::a][contains(@aria-label,'Next') or contains(@title,'Next')])[1]"),
    ]:
        try:
            nxt = WebDriverWait(driver, T.short).until(EC.element_to_be_clickable((by, sel)))
            driver.execute_script("arguments[0].click();", nxt)
            end = time.time() + T.med
            while time.time() < end:
                now = get_period_label(driver)
                if now and now != before: return True
                time.sleep(0.1)
        except: pass
    return False

# ===== Google Calendar =====
def get_calendar_service():
    creds = None
    BASE_DIR = getattr(sys, '_MEIPASS', os.path.abspath("."))
    TOKEN_PATH = os.path.join(BASE_DIR, 'token.json')
    CRED_PATH  = os.path.join(BASE_DIR, 'credentials.json')

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try: creds.refresh(Request())
            except RefreshError:
                print("⚠️ Re-auth required."); os.remove(TOKEN_PATH); creds = None
        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(CRED_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
            with open(TOKEN_PATH, 'w') as f: f.write(creds.to_json())

    return build('calendar', 'v3', credentials=creds)

def discord_notify(lines):
    if not DISCORD_WEBHOOK_URL or not lines: return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": "📅 **Schedule Update:**\n" + "\n".join(lines)}, timeout=10)
    except: pass

def gc_sync(calendar: Calendar, calendar_id='primary'):
    svc = get_calendar_service()
    now = datetime.utcnow()
    time_min = (now - timedelta(days=30)).isoformat() + 'Z'
    time_max = (now + timedelta(days=30)).isoformat() + 'Z'

    items = svc.events().list(calendarId=calendar_id, timeMin=time_min, timeMax=time_max,
                              singleEvents=True, orderBy='startTime').execute().get('items', [])
    lows = [e for e in items if e.get('summary') == "Lowe's 🛠️"]

    # delete existing Lowe's events
    deleted_dates = set()
    for e in lows:
        start = e['start'].get('dateTime')
        if not start: continue
        deleted_dates.add(start[:10])
        try: svc.events().delete(calendarId=calendar_id, eventId=e['id']).execute()
        except: pass

    added_dates = set()
    for ev in calendar.events:
        s = ev.begin.format('YYYY-MM-DDTHH:mm:ss')
        e = ev.end.format('YYYY-MM-DDTHH:mm:ss')
        body = {
            'summary': ev.name,
            'start': {'dateTime': s, 'timeZone': TZ},
            'end':   {'dateTime': e, 'timeZone': TZ}
        }
        try:
            svc.events().insert(calendarId=calendar_id, body=body).execute()
            added_dates.add(s[:10])
        except: pass

    changed = sorted(added_dates | deleted_dates)
    lines = []
    for d in changed:
        if d in added_dates and d in deleted_dates: lines.append(f"🔁 Updated shift on {d}")
        elif d in added_dates:                      lines.append(f"➕ New shift on {d}")
        else:                                       lines.append(f"❌ Removed shift on {d}")
    return lines

# ===== Parsing (condensed; keeps robust FC overlay path, minimal chatter) =====
def extract_month_year(soup):
    text = soup.get_text(" ", strip=True)
    m = MONTH_YEAR_RX.search(text)
    if m: return (MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
    now = datetime.now(); return (now.month, now.year)

def _is_hidden(tag):
    while tag:
        if tag.get("aria-hidden") == "true": return True
        st = (tag.get("style") or "").lower()
        if "display:none" in st or "visibility:hidden" in st: return True
        tag = tag.parent
    return False

def resolve_date_for_event_td(td):
    # find sibling table with td[data-date] in same row/col
    skel = td.find_parent("table")
    tr = td.find_parent("tr")
    if not skel or not tr: return None
    try:
        tbody = tr.find_parent("tbody") or skel
        rows = tbody.find_all("tr", recursive=False) or tbody.find_all("tr")
        row_idx = rows.index(tr)
        cols = tr.find_all("td", recursive=False) or tr.find_all("td")
        col_idx = cols.index(td)
    except: return None

    container = skel.parent
    day_grid = None
    for t in container.find_all("table"):
        if t.select_one("td[data-date]"): day_grid = t; break
    if not day_grid: return None

    dg_body = day_grid.find("tbody") or day_grid
    dg_rows = dg_body.find_all("tr", recursive=False) or dg_body.find_all("tr")
    if row_idx >= len(dg_rows): return None
    dg_cols = dg_rows[row_idx].find_all("td", recursive=False) or dg_rows[row_idx].find_all("td")
    if col_idx >= len(dg_cols): return None
    return dg_cols[col_idx].get("data-date")

def parse_view(html):
    soup = BeautifulSoup(html, "html.parser")
    events, seen = [], set()

    # FullCalendar overlay cells containing <span class="fc-time"> with "h:mm am - h:mm pm"
    event_tds = []
    for sp in soup.select("span.fc-time"):
        td = sp.find_parent("td")
        if td and not _is_hidden(td) and td not in event_tds:
            event_tds.append(td)

    for td in event_tds:
        date_iso = resolve_date_for_event_td(td)
        if not date_iso: continue
        y, m, d = map(int, date_iso.split("-"))
        for sp in td.select("span.fc-time"):
            mobj = TIME_RANGE_RX.search(sp.get_text(" ", strip=True) or "")
            if not mobj: continue
            s_str, e_str = mobj.group(1).lower(), mobj.group(2).lower()
            try:
                sdt = datetime.strptime(f"{y:04d}-{m:02d}-{d:02d} {s_str}", "%Y-%m-%d %I:%M %p")
                edt = datetime.strptime(f"{y:04d}-{m:02d}-{d:02d} {e_str}", "%Y-%m-%d %I:%M %p")
                if edt <= sdt: edt += timedelta(days=1)
                key = (sdt, edt)
                if key not in seen:
                    seen.add(key); events.append((sdt, edt, "Lowe's 🛠️"))
            except: pass

    return events

# ===== Main =====
def main():
    if not (USERNAME and PASSWORD and PIN):
        print("❌ Set LOWES_USER, LOWES_PASS, LOWES_PIN env vars."); return

    d = driver_new()
    print("▶️  Logging in…")
    d.get('https://www.myloweslife.com')
    WebDriverWait(d, 15).until(EC.presence_of_element_located((By.ID, "idToken2")))
    d.find_element(By.ID, 'idToken1').send_keys(USERNAME)
    d.find_element(By.ID, 'idToken2').send_keys(PASSWORD)
    d.find_element(By.ID, 'loginButton_0').click()
    WebDriverWait(d, 30).until(EC.invisibility_of_element_located((By.ID, "idToken2")))
    WebDriverWait(d, 15).until(EC.presence_of_element_located((By.ID, "idToken1")))
    d.find_element(By.ID, 'idToken1').send_keys(PIN)
    d.find_element(By.ID, 'loginButton_0').click()
    print("✅ Logged in.")

    # open UKG
    print("▶️  Opening UKG…")
    if not click_view_my_schedule_link(d): raise RuntimeError("UKG tile not found")
    time.sleep(0.3)
    if len(d.window_handles) > 1: d.switch_to.window(d.window_handles[-1])

    # wait calendar
    if not on_schedule_page_strict(d): raise RuntimeError("Calendar not detected")
    print("✅ On calendar.")

    # dump current + next
    curr_html = d.page_source
    curr_html_path = f"my_schedule_raw_{timestamp}.html"
    curr_png_path  = f"my_schedule_{timestamp}.png"
    with open(curr_html_path, "w", encoding="utf-8") as f: f.write(curr_html)
    d.save_screenshot(curr_png_path)
    print(f"💾 Saved current period: {curr_html_path} / {curr_png_path}")

    next_html = None
    if click_next_and_wait_change(d):
        next_html = d.page_source
        n_ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        nxt_html_path = f"my_schedule_raw_next_{n_ts}.html"
        nxt_png_path  = f"my_schedule_next_{n_ts}.png"
        with open(nxt_html_path, "w", encoding="utf-8") as f: f.write(next_html)
        d.save_screenshot(nxt_png_path)
        print(f"➡️  Saved next period: {nxt_html_path} / {nxt_png_path}")
    else:
        print("⚠️ Next period not available.")

    # parse
    cal = Calendar()
    all_events = parse_view(curr_html) + (parse_view(next_html) if next_html else [])
    uniq = {}
    for sdt, edt, label in all_events:
        key = (sdt.date(), sdt.time(), edt.time(), label)
        if key not in uniq: uniq[key] = (sdt, edt, label)
    all_events = list(uniq.values())

    for sdt, edt, label in all_events:
        ev = Event(); ev.name = label; ev.begin = sdt; ev.end = edt; cal.events.add(ev)

    print(f"✅ Parsed {len(all_events)} shift(s).")

    # write .ics (optional artifact)
    ics_path = f"schedule_{timestamp}.ics"
    with open(ics_path, 'w', encoding='utf-8') as f: f.write(str(cal))
    print(f"📄 ICS written: {ics_path}")

    # sync → Google Calendar
    if cal.events:
        print("▶️  Syncing Google Calendar…")
        changes = gc_sync(cal)
        if changes:
            print("✅ Calendar updated:")
            for line in changes: print("   " + line)
            discord_notify(changes)
        else:
            print("✅ No changes needed.")
    else:
        print("⏭️ Skipping sync (no shifts).")

    d.quit()
    print("🏁 Done.")

if __name__ == "__main__":
    main()
