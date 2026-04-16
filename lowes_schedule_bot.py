#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lowes schedule scraper — cleaned single-file version.
Run: python lowes_schedule_bot.py [--debug] [--no-calendar]
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from ics import Calendar, Event

from datetime import datetime, timedelta
from types import SimpleNamespace
import time, requests, os, re, sys, traceback, json, arrow, argparse, schedule, atexit

# Google Calendar libs are optional — only needed if --no-calendar is not set
try:
    from google.oauth2.credentials import Credentials
    from google.auth.exceptions import RefreshError
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

VERSION = "v3.6.0"

# --------------------------
# Config / Env
# --------------------------
TZ = "America/New_York"  # Placeholder until config loads
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# --------------------------
# CLI Args
# --------------------------
def parse_args():
    parser = argparse.ArgumentParser(description="Lowe's Schedule Bot")
    parser.add_argument("--debug",       action="store_true", help="Enable debug mode (dumps HTML/PNG)")
    parser.add_argument("--reset",       action="store_true", help="Reset configuration and tokens")
    parser.add_argument("--no-calendar", action="store_true", help="Skip Google Calendar sync (schedule scrape only)")
    return parser.parse_args()

ARGS = parse_args()
DEBUG = ARGS.debug
SKIP_CALENDAR = ARGS.no_calendar or not GOOGLE_AVAILABLE

CONFIG_DIR  = "data"
LOGS_DIR    = os.path.join(CONFIG_DIR, "logs")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
LOCK_FILE   = os.path.join(CONFIG_DIR, "lowes_bot.lock")

# --------------------------
# Single-instance guard
# --------------------------
def _is_docker():
    return os.path.exists("/.dockerenv")

def acquire_instance_lock():
    """
    Prevents multiple instances from running simultaneously.
    Uses a PID file; if the stored PID is no longer alive the lock is considered stale.
    In Docker, the PID lock is skipped — Docker itself guarantees single-instance
    and PIDs are reused across container restarts which causes false positives.
    """
    if _is_docker():
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
        atexit.register(_release_lock)
        return True
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)   # raises OSError if the process is gone
            return False           # process is alive — another instance is running
        except (OSError, ValueError):
            pass                   # stale lock — overwrite it
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    atexit.register(_release_lock)
    return True

def _release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE) as f:
                if int(f.read().strip()) == os.getpid():
                    os.remove(LOCK_FILE)
    except Exception:
        pass

# --------------------------
# Config loader
# --------------------------
def load_config():
    for d in [CONFIG_DIR, LOGS_DIR]:
        os.makedirs(d, exist_ok=True)

    config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
            print(f"✅ Loaded configuration from {CONFIG_FILE}")
        except Exception as e:
            print(f"⚠️ Error loading config: {e}")

    def get_val(key, prompt_text, default=None, required=False):
        val = os.getenv(key) or config.get(key)
        if not val and (default is None or required):
            try:
                print(f"📝 Setup Required: {prompt_text}")
                val = input(f"{prompt_text}: ").strip()
                if val:
                    config[key] = val
            except (EOFError, KeyboardInterrupt):
                if required and default is None:
                    print(f"❌ Error: {key} is required but could not prompt for input.")
                    sys.exit(1)
        return val or default

    username       = get_val("LOWES_USERNAME",        "Enter Lowe's Sales ID",                                        required=True)
    password       = get_val("LOWES_PASSWORD",        "Enter Lowe's Password",                                        required=True)
    pin            = get_val("LOWES_PIN",             "Enter 4-digit PIN",                                            required=True)
    tz_val         = get_val("TZ",                    "Enter Timezone (e.g. America/New_York)",                       default="America/New_York")
    webhook        = get_val("LOWES_DISCORD_WEBHOOK", "Enter Discord Webhook (optional)",                             default="")
    retention_days = int(get_val("LOG_RETENTION_DAYS", "Enter Log Retention Days",                                   default="7"))

    global TZ
    try:
        arrow.now(tz_val)
        TZ = tz_val
    except Exception:
        print(f"⚠️  INVALID TIMEZONE: '{tz_val}'. Defaulting to 'America/Los_Angeles'.")
        TZ = "America/Los_Angeles"
        config["TZ"] = TZ

    run_mode  = os.getenv("RUN_MODE")  or config.get("RUN_MODE",  "once")
    run_value = os.getenv("RUN_VALUE") or config.get("RUN_VALUE", "")

    if run_mode == "daily"    and not run_value: run_value = "08:00"
    if run_mode == "interval" and not run_value: run_value = "4"

    if username and password:
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump({
                    "LOWES_USERNAME":        username,
                    "LOWES_PASSWORD":        password,
                    "LOWES_PIN":             pin,
                    "TZ":                    TZ,
                    "LOWES_DISCORD_WEBHOOK": webhook,
                    "LOG_RETENTION_DAYS":    retention_days,
                    "RUN_MODE":              run_mode,
                    "RUN_VALUE":             run_value,
                }, f, indent=2)
        except Exception:
            pass

    return username, password, pin, webhook, retention_days, run_mode, run_value

# --------------------------
# Reset flag — handled before driver creation
# --------------------------
if ARGS.reset:
    print("🔄 Resetting configuration...")
    for fname in ["config.json", "token.json", "credentials.json"]:
        path = os.path.join(CONFIG_DIR, fname)
        if os.path.exists(path):
            try:
                os.remove(path)
                print(f"   Deleted {fname}")
            except Exception as e:
                print(f"   Failed to delete {fname}: {e}")
    print("✅ Reset complete. Please re-run to setup.")
    sys.exit(0)

USERNAME, PASSWORD, PIN, DISCORD_WEBHOOK_URL, LOG_RETENTION_DAYS, RUN_MODE, RUN_VALUE = load_config()

def dprint(*args):
    if DEBUG:
        print(*args)

# --------------------------
# Selenium — lazy creation
# --------------------------
driver = None   # created in __main__, never at import time

def create_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-background-networking")
    opts.add_argument("--disable-default-apps")
    opts.add_argument("--disable-sync")
    opts.add_argument("--no-first-run")
    opts.add_argument("--mute-audio")
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")
    # In Docker (Debian), chromium is installed as /usr/bin/chromium, not chrome
    for candidate in ("/usr/bin/chromium", "/usr/bin/chromium-browser"):
        if os.path.exists(candidate):
            opts.binary_location = candidate
            break
    return webdriver.Chrome(options=opts)

T = SimpleNamespace(short=1.0, med=4.0)

# --------------------------
# Click / window helpers
# --------------------------
def js_click(el):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    except Exception:
        pass
    try:
        driver.execute_script("arguments[0].click();", el)
    except Exception:
        el.click()

def switch_to_new_window(old_handles, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        now = driver.window_handles
        if len(now) > len(old_handles):
            new = [h for h in now if h not in old_handles][-1]
            driver.switch_to.window(new)
            return True
        time.sleep(0.2)
    return False

def wait_for_any(locators, timeout):
    end = time.time() + timeout
    last_err = None
    while time.time() < end:
        for by, sel in locators:
            try:
                el = WebDriverWait(driver, 0.6).until(EC.presence_of_element_located((by, sel)))
                return el
            except Exception as e:
                last_err = e
        time.sleep(0.1)
    if last_err:
        raise last_err

# --------------------------
# Save view + Diagnostics
# --------------------------
def save_view(tag_prefix="my_schedule"):
    ts        = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    html      = driver.page_source
    html_path = os.path.join(LOGS_DIR, f"{tag_prefix}_raw_{ts}.html")
    png_path  = os.path.join(LOGS_DIR, f"{tag_prefix}_{ts}.png")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    driver.save_screenshot(png_path)
    print(f"💾 Saved: {html_path}")
    print(f"🖼️ Saved: {png_path}")
    return html

def debug_dump(tag):
    return save_view(f"debug_{tag}")

def diagnostic_calendar_snapshot(tag="diag"):
    checks = [
        ".fc-event",
        ".fc-time",
        ".fc-daygrid-day",
        "table",
        ".employee-view, #mySchedule, .my-schedule, [data-view='my-schedule']",
    ]
    found = {}
    for sel in checks:
        try:
            found[sel] = len(driver.find_elements(By.CSS_SELECTOR, sel))
        except Exception:
            found[sel] = 0

    print("🔍 Calendar diagnostics:")
    for sel, cnt in found.items():
        print(f"  {sel}: {cnt}")
        if cnt:
            try:
                el     = driver.find_elements(By.CSS_SELECTOR, sel)[0]
                sample = (el.get_attribute("outerText") or "")[:240].replace("\n", " ")
                print(f"  sample ({sel}): {sample}")
            except Exception as e:
                print(f"  sample ({sel}): <error: {e}>")

    try:
        cal = None
        for candidate in (".fc-daygrid", ".fc-timegrid", ".employee-view", "#mySchedule", "table"):
            try:
                cal = driver.find_element(By.CSS_SELECTOR, candidate)
                break
            except Exception:
                cal = None
        if cal:
            snippet = cal.get_attribute("outerHTML")
            fname   = os.path.join(LOGS_DIR, f"snippet_{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
            with open(fname, "w", encoding="utf-8") as f:
                f.write(snippet)
            print(f"💾 Saved {fname} ({len(snippet)} bytes)")
        else:
            print("⚠️ No calendar container candidate found for snippet.")
    except Exception as e:
        print("⚠️ diagnostic snippet save failed:", e)

def cleanup_old_artifacts():
    if LOG_RETENTION_DAYS < 0:
        return
    print(f"🧹 Running log cleanup (Retention: {LOG_RETENTION_DAYS} days)...")
    now    = time.time()
    cutoff = now - (LOG_RETENTION_DAYS * 86400)
    count  = 0
    try:
        for filename in os.listdir(LOGS_DIR):
            file_path = os.path.join(LOGS_DIR, filename)
            if os.path.isfile(file_path) and os.path.getmtime(file_path) < cutoff:
                os.remove(file_path)
                count += 1
        if count > 0:
            print(f"   Done. Removed {count} old artifact(s).")
    except Exception as e:
        print(f"⚠️ Cleanup failed: {e}")

# --------------------------
# Login
# --------------------------
def login_to_portal():
    print("🔑 Authenticating with Lowe's Portal...")
    driver.get("https://www.myloweslife.com")

    try:
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "idToken2")))
    except Exception:
        if "Home" in driver.title or "MyLowesLife" in driver.page_source:
            print("✅ System: Session authenticated.")
            return True
        debug_dump("login_portal_timeout")
        raise Exception("Timed out waiting for initial login page.")

    try:
        print("   -> Entering credentials...")
        driver.find_element(By.ID, "idToken1").send_keys(USERNAME)
        driver.find_element(By.ID, "idToken2").send_keys(PASSWORD)

        login_btn = driver.find_element(By.ID, "loginButton_0")
        try:
            login_btn.click()
        except Exception:
            js_click(login_btn)

        print("   -> Authentication stage 1 submitted. Waiting for PIN prompt...")
        WebDriverWait(driver, 30).until(EC.invisibility_of_element_located((By.ID, "idToken2")))
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "idToken1")))

        print("   -> Entering security PIN...")
        driver.find_element(By.ID, "idToken1").send_keys(PIN)

        final_btn = driver.find_element(By.ID, "loginButton_0")
        try:
            final_btn.click()
        except Exception:
            js_click(final_btn)

        time.sleep(3)
        print("✅ System: Portal authentication successful.")
        return True
    except Exception as e:
        debug_dump("login_failure")
        raise Exception(f"Login failed: {str(e)}")

def open_ukg_tile():
    def try_here():
        x1 = "//span[@class='toolname' and normalize-space()='UKG']"
        x2 = "//span[contains(@class,'toolname') and contains(normalize-space(),'UKG')]"
        x3 = "//img[contains(@src,'UKG-Avatar-social')]/ancestor::*[self::a or self::button or @role='button'][1]"
        for xp in (x1, x2):
            try:
                span      = WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.XPATH, xp)))
                try:
                    clickable = span.find_element(By.XPATH, "ancestor::*[self::a or self::button or @role='button'][1]")
                except Exception:
                    clickable = span
                old = driver.window_handles[:]
                js_click(clickable)
                switch_to_new_window(old, timeout=8)
                return True
            except Exception:
                pass
        try:
            card = WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.XPATH, x3)))
            old  = driver.window_handles[:]
            js_click(card)
            switch_to_new_window(old, timeout=8)
            return True
        except Exception:
            return False

    if try_here():
        return True

    try:
        frames = driver.find_elements(By.TAG_NAME, "iframe")
    except Exception:
        frames = []
    for fr in frames:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(fr)
            if try_here():
                driver.switch_to.default_content()
                return True
        except Exception:
            continue
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return False

# --------------------------
# Helpers
# --------------------------
TIME_RANGE_RX = re.compile(
    r"(\d{1,2}:\d{2}\s*(?:am|pm)?)\s*[-–—]\s*(\d{1,2}:\d{2}\s*(?:am|pm))",
    re.IGNORECASE
)

# Pay codes and labels that mean the employee is NOT working.
# When any of these appear in the text surrounding a time range, skip it.
NON_WORK_RX = re.compile(
    r"\b("
    r"unpaid|jury(\s+duty)?|holiday|vacation|sick(\s+(day|leave))?|"
    r"give\s*back|personal(\s+day)?|bereavement|leave(\s+of\s+absence)?|"
    r"fmla|loa|floating|comp(\s+day)?|pto|time\s*off|"
    r"christmas|thanksgiving|new\s*year|labor\s*day|memorial\s*day|"
    r"independence\s*day|mlk|martin\s*luther|veterans\s*day|"
    r"columbus\s*day|presidents\s*day|easter|good\s*friday"
    r")\b",
    re.IGNORECASE
)

def is_non_work(text):
    """Return True if text contains a pay code indicating a day off."""
    return bool(NON_WORK_RX.search(text or ""))

def click_next_and_wait_change():
    def grab_label():
        try:
            el = driver.find_element(By.CSS_SELECTOR, "[role='grid']")
            return el.get_attribute("outerText")[:80]
        except Exception:
            return str(time.time())

    before = grab_label()
    for by, sel in [
        (By.XPATH, "((//*[contains(normalize-space(.),'Previous') and contains(normalize-space(.),'Next')])[1]//*[self::button or self::a][normalize-space()='Next'])[1]"),
        (By.XPATH, "((//*[contains(normalize-space(.),'Previous') and contains(normalize-space(.),'Next')])[1]//*[self::button or self::a][contains(@aria-label,'Next') or contains(@title,'Next')])[1]"),
    ]:
        try:
            nxt = WebDriverWait(driver, T.short).until(EC.element_to_be_clickable((by, sel)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", nxt)
            driver.execute_script("arguments[0].click();", nxt)
            end = time.time() + T.med
            while time.time() < end:
                now = grab_label()
                if now and now != before:
                    return True
                time.sleep(0.12)
        except Exception:
            pass
    return False

def parse_fullcalendar_period(view_html):
    soup   = BeautifulSoup(view_html, "html.parser")
    events = []
    seen   = set()

    def add_event_if_new(start_dt, end_dt, source_text=None, raw_text=""):
        if is_non_work(raw_text):
            dprint(f"   ⏭️  Skipped non-work entry ({source_text}): {raw_text[:80]!r}")
            return
        start_dt = start_dt.replace(second=0, microsecond=0)
        end_dt   = end_dt.replace(second=0, microsecond=0)
        if end_dt <= start_dt:
            end_dt = end_dt.shift(days=1)
        key = (start_dt.isoformat(), end_dt.isoformat())
        if key in seen:
            return
        seen.add(key)
        events.append((start_dt, end_dt, "Lowe's 🛠️"))
        if source_text:
            print(f"   🔍 Identified: {source_text} -> {start_dt.format('HH:mm')} to {end_dt.format('HH:mm')}")

    def parse_dt(date_iso, time_str):
        for fmt in ("%Y-%m-%d %I:%M %p", "%Y-%m-%d %I:%M%p"):
            try:
                dt = datetime.strptime(f"{date_iso} {time_str}", fmt)
                return arrow.get(dt, TZ)
            except Exception:
                continue
        return None

    # 1) JS DOM column→date map
    col_to_date = {}
    try:
        js = """
        (function(){
          var out=[];
          var ths = document.querySelectorAll('table thead tr td');
          if(!ths || ths.length===0){
            ths = document.querySelectorAll('.fc-daygrid-day');
          }
          ths.forEach(function(td){
            var d = td.getAttribute('data-date') || (td.dataset && td.dataset.date) || null;
            out.push({date:d, cls: td.className||'', text: (td.innerText||td.textContent||'').trim()});
          });
          return out;
        })();
        """
        cols = driver.execute_script(js)
        if cols and isinstance(cols, list):
            for i, c in enumerate(cols, start=1):
                if c.get("date") and re.match(r"^\d{4}-\d{2}-\d{2}$", c["date"]):
                    col_to_date[i] = c["date"]
                else:
                    col_to_date[i] = {"text": c.get("text", ""), "cls": c.get("cls", "")}
    except Exception:
        col_to_date = {}

    pure_map = {k: v for k, v in col_to_date.items() if isinstance(v, str)}
    if pure_map:
        col_to_date = pure_map

    # 2) HTML header fallback
    if not any(isinstance(v, str) for v in col_to_date.values()):
        header_row = soup.select_one("table thead tr")
        month_year = None
        tb = (soup.select_one("span.toolbar-text.element-title")
              or soup.select_one(".fc-toolbar h2")
              or soup.select_one(".fc-toolbar .fc-center h2"))
        if tb:
            m = re.search(r"([A-Za-z]{3,9}\s+\d{4})", tb.get_text(strip=True))
            if m:
                month_year = m.group(1)
        if header_row:
            for idx, td in enumerate(header_row.find_all("td", recursive=False), start=1):
                d_attr = td.get("data-date")
                if d_attr and re.match(r"^\d{4}-\d{2}-\d{2}$", d_attr):
                    col_to_date[idx] = d_attr
                else:
                    txt = td.get_text(" ", strip=True)
                    m   = re.match(r"^(\d{1,2})$", txt or "")
                    if m and month_year:
                        try:
                            for fmt in ("%b %Y %d", "%B %Y %d"):
                                try:
                                    dt = datetime.strptime(f"{month_year} {int(m.group(1))}", fmt)
                                    col_to_date[idx] = dt.strftime("%Y-%m-%d")
                                    break
                                except Exception:
                                    continue
                        except Exception:
                            pass

    # 3) Table-based parsing
    try:
        if col_to_date:
            for r in soup.select("table tbody tr"):
                for col_idx, td in enumerate(r.find_all("td", recursive=False), start=1):
                    date_iso = col_to_date.get(col_idx)
                    if not date_iso or isinstance(date_iso, dict):
                        continue
                    cell_text  = td.get_text(" ", strip=True)
                    time_nodes = td.select("span.fc-time, .fc-time, div.time, span.time")
                    for sp in time_nodes:
                        m = TIME_RANGE_RX.search(sp.get_text(" ", strip=True) or "")
                        if m:
                            sdt = parse_dt(date_iso, m.group(1).lower())
                            edt = parse_dt(date_iso, m.group(2).lower())
                            if sdt and edt:
                                add_event_if_new(sdt, edt, f"Grid table cell ({date_iso})", raw_text=cell_text)
                    if not time_nodes:
                        for m in TIME_RANGE_RX.finditer(cell_text or ""):
                            sdt = parse_dt(date_iso, m.group(1).lower())
                            edt = parse_dt(date_iso, m.group(2).lower())
                            if sdt and edt:
                                add_event_if_new(sdt, edt, f"Grid table fallback ({date_iso})", raw_text=cell_text)
            if events:
                dprint("parse: used table-based strategy (DOM header map)")
                return events
    except Exception as ex:
        dprint("parse table-based error:", ex)

    # 4) Div/daygrid strategy
    try:
        for day in soup.select("div.fc-daygrid-day, div.fc-day, div.fc-daygrid-day-frame"):
            date_iso = day.get("data-date")
            if not date_iso:
                m = re.search(r"(\d{4}-\d{2}-\d{2})", day.get("aria-label") or "")
                if m:
                    date_iso = m.group(1)
            if not date_iso:
                continue
            for ev in day.select(".fc-event, .fc-daygrid-event, .fc-list-item, .event"):
                ev_text = ev.get_text(" ", strip=True)
                m       = TIME_RANGE_RX.search(ev_text or "")
                if m:
                    sdt = parse_dt(date_iso, m.group(1).lower())
                    edt = parse_dt(date_iso, m.group(2).lower())
                    if sdt and edt:
                        add_event_if_new(sdt, edt, f"DayGrid div ({date_iso})", raw_text=ev_text)
        if events:
            dprint("parse: used div-based daygrid strategy")
            return events
    except Exception as ex:
        dprint("parse div-based error:", ex)

    # 5) Global brute-force scan
    try:
        for node in soup.find_all(string=TIME_RANGE_RX):
            m = TIME_RANGE_RX.search(node)
            if not m:
                continue
            candidate_date = None
            ancestor_text  = ""
            curr = node.parent
            for _ in range(10):
                if not curr:
                    break
                d = curr.get("data-date")
                if d and re.match(r"^\d{4}-\d{2}-\d{2}$", d):
                    candidate_date = d
                    break
                t = curr.get_text(" ", strip=True)
                if len(t) < 200:
                    ancestor_text = t
                    m_date = re.search(r"(\d{4}-\d{2}-\d{2})", t)
                    if m_date:
                        candidate_date = m_date.group(1)
                        break
                curr = curr.parent
            if candidate_date:
                sdt = parse_dt(candidate_date, m.group(1).lower())
                edt = parse_dt(candidate_date, m.group(2).lower())
                if sdt and edt:
                    add_event_if_new(sdt, edt, f"Brute-force scan ({candidate_date})",
                                     raw_text=ancestor_text or str(node))
        if events:
            dprint("parse: used global brute-force scanner")
            return events
    except Exception as ex:
        dprint("parse brute-force error:", ex)

    return events

def scrape_shifts_from_aside(max_clicks=None):
    found = []
    tds   = driver.find_elements(By.CSS_SELECTOR, "td[data-date]")
    if not tds:
        tds = driver.find_elements(By.CSS_SELECTOR, "div.fc-daygrid-day[data-date], div[data-date]")

    clicks = 0
    for td in tds:
        if max_clicks and clicks >= max_clicks:
            break
        date_iso = td.get_attribute("data-date")
        if not date_iso:
            continue
        if len(found) > 50:
            print(f"⚠️ Scavenger Guard: Found {len(found)} shifts in aside. Truncating.")
            break
        clicks += 1
        try:
            try:
                js_click(td.find_element(By.CSS_SELECTOR, ".fc-day-number"))
            except Exception:
                js_click(td)
            time.sleep(0.5)

            panel_text = ""
            for sel in (".shift-detail", ".shift-info", ".employee-view-aside", ".krn-list"):
                try:
                    el = driver.find_element(By.CSS_SELECTOR, sel)
                    panel_text = el.get_attribute("innerText") or ""
                    if panel_text.strip():
                        break
                except Exception:
                    panel_text = ""

            if not panel_text:
                continue

            day_count = 0
            for m in TIME_RANGE_RX.finditer(panel_text):
                if day_count >= 3:
                    break
                try:
                    sdt_naive = datetime.strptime(f"{date_iso} {m.group(1).lower()}", "%Y-%m-%d %I:%M %p")
                    edt_naive = datetime.strptime(f"{date_iso} {m.group(2).lower()}", "%Y-%m-%d %I:%M %p")
                    sdt = arrow.get(sdt_naive, TZ)
                    edt = arrow.get(edt_naive, TZ)
                    if edt <= sdt:
                        edt = edt.shift(days=1)
                    if is_non_work(panel_text):
                        dprint(f"   ⏭️  Skipped non-work entry (aside {date_iso}): {panel_text[:80]!r}")
                        break
                    found.append((sdt, edt, "Lowe's 🛠️"))
                    day_count += 1
                except Exception:
                    continue
        except Exception:
            dprint("aside scrape error:", traceback.format_exc())
        finally:
            time.sleep(0.12)
    return found

def run_scrape_cycle():
    driver.get("https://lowescompanies-sso.prd.mykronos.com/ess#/")
    print("🡺 Navigated directly to schedule portal")

    try:
        WebDriverWait(driver, 8).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, "td[data-date], .fc-daygrid-day")
        )
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".fc-event, .fc-daygrid-event, .event"))
            )
            time.sleep(1.0)
        except Exception:
            print("⚠️ No events appeared within 5s (might be empty schedule).")
    except Exception:
        pass

    diagnostic_calendar_snapshot("before_save")
    time.sleep(0.9)

    found_events = []
    for i in range(1, 4):
        dprint(f"--- Crawling Page {i} ---")
        current_html = save_view(f"my_schedule_p{i}")
        grid_events  = parse_fullcalendar_period(current_html)
        if grid_events:
            print(f"🧩 Page {i}: Found {len(grid_events)} event(s) via Grid parser.")
            found_events.extend(grid_events)
        else:
            print(f"⚠️ Page {i}: Grid parser found 0 events.")

        if i < 3:
            if click_next_and_wait_change():
                dprint(f"Successfully navigated to page {i+1}")
                time.sleep(3.0)
                try:
                    WebDriverWait(driver, 5).until(
                        lambda d: d.find_elements(By.CSS_SELECTOR, "td[data-date], .fc-event")
                    )
                except Exception:
                    pass
            else:
                dprint(f"Pagination stop: Next button not found at page {i}.")
                break

    final_events = sorted(set(found_events), key=lambda x: (x[0], x[1]))
    if len(final_events) > 100:
        print(f"⚠️ Global Scavenger Alert: {len(final_events)} shifts found. Truncating to 100.")
        final_events = final_events[:100]
    return final_events

# --------------------------
# Google Calendar sync
# --------------------------
def get_calendar_service():
    if not GOOGLE_AVAILABLE:
        print("❌ Google Calendar libraries not installed. Run: pip install google-api-python-client google-auth-oauthlib")
        return None

    creds            = None
    TOKEN_PATH       = os.path.join(CONFIG_DIR, "token.json")
    CREDENTIALS_PATH = os.path.join(CONFIG_DIR, "credentials.json")

    if not os.path.exists(CREDENTIALS_PATH):
        env_keys = {k.upper(): v for k, v in os.environ.items()}
        env_cid  = env_keys.get("GOOGLE_CLIENT_ID")
        env_csec = env_keys.get("GOOGLE_CLIENT_SECRET")

        if env_cid and env_csec:
            env_cid  = env_cid.strip().strip('"').strip("'")
            env_csec = env_csec.strip().strip('"').strip("'")
            print("🔹 Authenticating with Google Credentials from environment...", flush=True)
            data = {"installed": {
                "client_id": env_cid, "project_id": "lowes-scheduler",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_secret": env_csec, "redirect_uris": ["http://localhost"],
            }}
            try:
                with open(CREDENTIALS_PATH, "w") as f:
                    json.dump(data, f)
                print("✅ Service credentials generated from environment.", flush=True)
            except Exception as e:
                print(f"❌ Failed to initialize credentials: {e}", flush=True)
        elif sys.stdin.isatty():
            print("\nℹ️  Setup: Manual Google Calendar authorization required.", flush=True)
            try:
                cid  = input("Enter Client ID: ").strip()
                csec = input("Enter Client Secret: ").strip()
                if cid and csec:
                    data = {"installed": {
                        "client_id": cid, "project_id": "lowes-scheduler",
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                        "client_secret": csec, "redirect_uris": ["http://localhost"],
                    }}
                    with open(CREDENTIALS_PATH, "w") as f:
                        json.dump(data, f)
                    print("✅ Credentials saved locally.", flush=True)
            except (EOFError, KeyboardInterrupt):
                print("🛑 Setup interrupted.", flush=True)
                return None
        else:
            print("❌ CRITICAL ERROR: Google Credentials not provided.", flush=True)
            return None

    if not os.path.exists(TOKEN_PATH):
        env_token = (os.getenv("GOOGLE_TOKEN_JSON") or "").strip().strip('"').strip("'")
        if env_token:
            print("🔹 Initializing Google Token from environment...", flush=True)
            try:
                with open(TOKEN_PATH, "w") as f:
                    json.dump(json.loads(env_token), f)
                print("✅ Token initialized.", flush=True)
            except Exception as e:
                print(f"❌ Failed to parse Google Token: {e}", flush=True)

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                print("⚠️ Token expired or revoked. Re-authentication required.")
                try:
                    os.remove(TOKEN_PATH)
                except Exception:
                    pass
                creds = None
        if not creds or not creds.valid:
            print("🔑 Opening browser for reauthorization...")
            flow  = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
            with open(TOKEN_PATH, "w") as token_file:
                token_file.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)

def send_discord_update(changes):
    if not DISCORD_WEBHOOK_URL or not changes:
        return
    msg = "📅 **Schedule Update:**\n" + "\n".join(changes)
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=10)
        print("📨 Sent Discord notification.")
    except Exception as e:
        print(f"❌ Failed to send Discord notification: {e}")

def sync_to_google_calendar(cal, calendar_id="primary"):
    if not cal.events:
        print("⏭️ Skipping Google Calendar sync (no parsed shifts).")
        return

    service = get_calendar_service()
    if not service:
        return

    earliest_parsed = min(ev.begin for ev in cal.events)
    time_min = earliest_parsed.shift(hours=-24).isoformat()
    time_max = earliest_parsed.shift(days=90).isoformat()

    all_events_g = service.events().list(
        calendarId=calendar_id,
        timeMin=time_min, timeMax=time_max,
        singleEvents=True, orderBy="startTime",
    ).execute().get("items", [])

    lowes_events = [e for e in all_events_g if e.get("summary") == "Lowe's 🛠️"]

    g_map = {}
    for e in lowes_events:
        st = e["start"].get("dateTime") or e["start"].get("date")
        et = e["end"].get("dateTime")   or e["end"].get("date")
        if st and et:
            s_utc = arrow.get(st).to("UTC").format("YYYY-MM-DDTHH:mm:ss")
            e_utc = arrow.get(et).to("UTC").format("YYYY-MM-DDTHH:mm:ss")
            g_map[(s_utc, e_utc)] = e["id"]

    p_map = {}
    for ev in cal.events:
        s_utc = ev.begin.to("UTC").format("YYYY-MM-DDTHH:mm:ss")
        e_utc = ev.end.to("UTC").format("YYYY-MM-DDTHH:mm:ss")
        p_map[(s_utc, e_utc)] = ev

    deleted_count = 0
    panic_limit   = 5
    deleted_dates = set()

    for (s, en), eid in g_map.items():
        if (s, en) not in p_map:
            if deleted_count >= panic_limit:
                print(f"⚠️ Panic Guard: Avoided deleting more than {panic_limit} shifts.")
                break
            try:
                service.events().delete(calendarId=calendar_id, eventId=eid).execute()
                deleted_dates.add(s[:10])
                deleted_count += 1
                print(f"🗑️ Deleted stale shift on {s[:10]} {s[11:]}")
            except Exception as e:
                print(f"❌ Failed to delete: {e}")

    added_dates = set()
    for (s_utc, e_utc), ev in p_map.items():
        if (s_utc, e_utc) not in g_map:
            try:
                s_local = ev.begin.format("YYYY-MM-DDTHH:mm:ss")
                e_local = ev.end.format("YYYY-MM-DDTHH:mm:ss")
                service.events().insert(calendarId=calendar_id, body={
                    "summary": ev.name,
                    "start": {"dateTime": s_local, "timeZone": TZ},
                    "end":   {"dateTime": e_local, "timeZone": TZ},
                }).execute()
                added_dates.add(s_local[:10])
                print(f"✅ Added new shift on {s_local[:10]} {s_local[11:]}–{e_local[11:]}")
            except Exception as e:
                print(f"❌ Failed to add event: {e}")

    changed_dates = sorted(added_dates | deleted_dates)
    if changed_dates:
        changes = []
        for d in changed_dates:
            if d in deleted_dates and d in added_dates:
                changes.append(f"🔁 Updated shift on {d}")
            elif d in deleted_dates:
                changes.append(f"❌ Removed shift on {d}")
            else:
                changes.append(f"➕ New shift on {d}")
        send_discord_update(changes)
    else:
        print("✅ No calendar changes; no Discord notification.")

# --------------------------
# Main task
# --------------------------
def main_task():
    print(f"\n--- Synchronization Process Initiated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
    cleanup_old_artifacts()

    try:
        login_to_portal()
    except Exception as e:
        print(f"❌ Login failed: {e}")
        return  # driver stays alive for the next scheduled run; quit handled in __main__

    all_events = []
    for attempt in range(1, 4):
        print(f"🔄 Scrape Attempt {attempt}/3...")
        try:
            all_events = run_scrape_cycle()
            if all_events:
                break
            print("⚠️ No shifts found in this attempt. Retrying...")
            time.sleep(3)
        except Exception as e:
            print(f"❌ Scrape cycle failed: {e}")
            time.sleep(3)

    if not all_events:
        print("❌ All scrape attempts failed. Skipping sync.")
        return

    calendar = Calendar()
    for start_dt, end_dt, label in all_events:
        ev       = Event()
        ev.name  = label
        ev.begin = start_dt
        ev.end   = end_dt
        calendar.events.add(ev)

    print(f"✅ Parsed {len(all_events)} shift(s).")

    ics_name = os.path.join(LOGS_DIR, f"schedule_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.ics")
    with open(ics_name, "w", encoding="utf-8") as f:
        f.write(str(calendar))
    print(f"🗂️ Calendar saved as {ics_name}")

    if SKIP_CALENDAR:
        print("⏭️ Skipping Google Calendar sync (--no-calendar or Google libs not installed).")
    else:
        sync_to_google_calendar(calendar)

    print(f"💤 Job finished at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# --------------------------
# Entry point
# --------------------------
if __name__ == "__main__":
    print(f"Lowe's Schedule Synchronization Service - {VERSION}")

    if not acquire_instance_lock():
        print("❌ Another instance is already running. Exiting.")
        sys.exit(1)

    # Timezone diagnostic
    print(f"🌍 Active Timezone: {TZ}")
    try:
        sys_tz = time.tzname[0]
        if TZ == "America/New_York" and sys_tz in ("PST", "PDT", "MST", "CST"):
            print(f"⚠️  WARNING: Bot is set to New York time but server is in {sys_tz}.")
    except Exception:
        pass

    if SKIP_CALENDAR and not ARGS.no_calendar:
        print("⚠️  Google Calendar libraries not found — running in schedule-only mode.")
        print("   Install them with: pip install google-api-python-client google-auth-oauthlib")

    driver = create_driver()

    try:
        if RUN_MODE == "once":
            main_task()
            print("Synchronization completed successfully. Exiting.")
        else:
            print(f"Schedule synchronization active: {RUN_MODE} {RUN_VALUE}")
            main_task()

            if RUN_MODE == "daily":
                schedule.every().day.at(RUN_VALUE).do(main_task)
                print(f"Next synchronization scheduled for {RUN_VALUE}")
            elif RUN_MODE == "interval":
                try:
                    h = int(RUN_VALUE)
                    schedule.every(h).hours.do(main_task)
                    print(f"Service running on a {h}-hour interval.")
                except ValueError:
                    print("❌ Configuration Error: Invalid interval value.")
                    sys.exit(1)

            print("System monitoring active. Waiting for scheduled tasks...")
            last_heartbeat = time.time()
            while True:
                schedule.run_pending()
                if time.time() - last_heartbeat > 600:
                    print(f"💓 Heartbeat: {datetime.now().strftime('%H:%M:%S')}")
                    last_heartbeat = time.time()
                time.sleep(10)

    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user.")
    except Exception as e:
        print(f"❌ Critical error: {e}", flush=True)
        traceback.print_exc()
    finally:
        print("🔻 Service is terminating.", flush=True)
        try:
            driver.quit()
        except Exception:
            pass
