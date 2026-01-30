#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lowes schedule scraper — cleaned single-file version.
Run: python lowes_schedule_bot.py [--debug]
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from ics import Calendar, Event

from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from datetime import datetime, timedelta
from types import SimpleNamespace
import pytesseract, time, requests, os, re, sys, traceback, json, arrow, argparse, schedule

VERSION = "v3.4.4"
# --------------------------
# Config / Env
# --------------------------
TZ = os.getenv("TZ", "America/New_York") # Default to NY if no TZ is set
SCOPES = ["https://www.googleapis.com/auth/calendar"]
# DISCORD_WEBHOOK_URL will be loaded from config or env

# --------------------------
# CLI Utils
# --------------------------
def parse_args():
    parser = argparse.ArgumentParser(description="Lowe's Schedule Bot")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode (dumps HTML/PNG)")
    parser.add_argument("--reset", action="store_true", help="Reset configuration and tokens")
    return parser.parse_args()

ARGS = parse_args()
DEBUG = ARGS.debug

CONFIG_DIR = "data"
LOGS_DIR = os.path.join(CONFIG_DIR, "logs")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

def load_config():
    # Ensure data and logs dir exist
    for d in [CONFIG_DIR, LOGS_DIR]:
        if not os.path.exists(d):
            os.makedirs(d)
    
    config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
            print(f"✅ Loaded configuration from {CONFIG_FILE}")
        except Exception as e:
            print(f"⚠️ Error loading config: {e}")

    # Helper: Environment wins, then saved config, then prompt if interactive & required
    def get_val(key, prompt_text, default=None, required=False):
        val = os.getenv(key) or config.get(key)
        
        # Only prompt if missing, interactive, and either no default or explicitly required
        if not val and sys.stdin.isatty() and (default is None or required):
            print(f"📝 Setup Required: {prompt_text}")
            val = input(f"{prompt_text}: ").strip()
            if val: config[key] = val
            
        return val or default

    username = get_val("LOWES_USERNAME", "Enter Lowe's Sales ID", required=True)
    password = get_val("LOWES_PASSWORD", "Enter Lowe's Password", required=True)
    pin      = get_val("LOWES_PIN", "Enter 4-digit PIN", required=True)
    webhook  = get_val("LOWES_DISCORD_WEBHOOK", "Enter Discord Webhook (optional)", default="")
    retention_days = int(get_val("LOG_RETENTION_DAYS", "Enter Log Retention Days", default="7"))
    
    # Schedule Configuration
    run_mode = os.getenv("RUN_MODE") or config.get("RUN_MODE", "once")
    run_value = os.getenv("RUN_VALUE") or config.get("RUN_VALUE", "")

    # Safety defaults
    if run_mode == "daily" and not run_value: run_value = "08:00"
    if run_mode == "interval" and not run_value: run_value = "4"

    # CRITICAL: ONLY save to config if we actually have some data to save.
    # This prevents Docker environments from accidentally clearing a valid config file.
    if username and password:
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump({
                    "LOWES_USERNAME": username,
                    "LOWES_PASSWORD": password,
                    "LOWES_PIN": pin,
                    "LOWES_DISCORD_WEBHOOK": webhook,
                    "LOG_RETENTION_DAYS": retention_days,
                    "RUN_MODE": run_mode,
                    "RUN_VALUE": run_value
                }, f, indent=2)
        except: pass


    return username, password, pin, webhook, retention_days, run_mode, run_value

if ARGS.reset:
    print("🔄 Resetting configuration...")
    for f in ["config.json", "token.json", "credentials.json"]:
        path = os.path.join(CONFIG_DIR, f)
        if os.path.exists(path):
            try:
                os.remove(path)
                print(f"   Deleted {f}")
            except Exception as e:
                print(f"   Failed to delete {f}: {e}")
    print("✅ Reset complete. Please re-run to setup.")
    sys.exit(0)

USERNAME, PASSWORD, PIN, DISCORD_WEBHOOK_URL, LOG_RETENTION_DAYS, RUN_MODE, RUN_VALUE = load_config()

# Tesseract path: inside Docker it will be just 'tesseract' usually, or configure via env
TESSERACT_PATH = os.getenv("TESSERACT_PATH", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
# If running in linux/docker, tesseract might just be on path
if os.name != 'nt':
    TESSERACT_PATH = "tesseract"

pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

def dprint(*args):
    if DEBUG:
        print(*args)

# --------------------------
# Selenium setup
# --------------------------
T = SimpleNamespace(short=1.0, med=4.0)
chrome_options = Options()
chrome_options.add_argument("--headless=new")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--window-size=1920,1080")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")
driver = webdriver.Chrome(options=chrome_options)

def wait_for_any(driver, locators, timeout):
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

def debug_dump(tag):
    if not DEBUG:
        return
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    try:
        try: driver.switch_to.default_content()
        except: pass
        html = driver.page_source
        with open(os.path.join(CONFIG_DIR, f"debug_{tag}_{ts}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        driver.save_screenshot(os.path.join(CONFIG_DIR, f"debug_{tag}_{ts}.png"))
        dprint(f"🧪 Debug dump: saved to {CONFIG_DIR}")
    except Exception as e:
        print(f"⚠️ debug_dump failed: {e}")

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
        try:
            el.click()
        except Exception:
            raise

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

# --------------------------
# Save view + Diagnostics
# --------------------------
def debug_dump(tag):
    return save_view(f"debug_{tag}")

def save_view(tag_prefix="my_schedule"):
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    html = driver.page_source
    html_path = os.path.join(LOGS_DIR, f"{tag_prefix}_raw_{ts}.html")
    png_path  = os.path.join(LOGS_DIR, f"{tag_prefix}_{ts}.png")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    driver.save_screenshot(png_path)
    print(f"💾 Saved: {html_path}")
    print(f"🖼️ Saved: {png_path}")
    return html

def diagnostic_calendar_snapshot(tag="diag"):
    checks = [
        (".fc-event"),
        (".fc-time"),
        (".fc-daygrid-day"),
        ("table"),
        (".employee-view, #mySchedule, .my-schedule, [data-view='my-schedule']"),
    ]
    found = {}
    for sel in checks:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            found[sel] = len(els)
        except Exception:
            found[sel] = 0

    print("🔍 Calendar diagnostics:")
    for sel, cnt in found.items():
        print(f"  {sel}: {cnt}")

    # sample text from first matched selector (if any)
    for sel, cnt in found.items():
        if cnt:
            try:
                el = driver.find_elements(By.CSS_SELECTOR, sel)[0]
                sample = (el.get_attribute("outerText") or "")[:240].replace("\n", " ")
                print(f"  sample ({sel}): {sample}")
            except Exception as e:
                print(f"  sample ({sel}): <error: {e}>")

    # Save focused snippet if possible
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
            fname = os.path.join(LOGS_DIR, f"snippet_{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
            with open(fname, "w", encoding="utf-8") as f:
                f.write(snippet)
            print(f"💾 Saved {fname} ({len(snippet)} bytes)")
        else:
            print("⚠️ No calendar container candidate found for snippet.")
    except Exception as e:
        print("⚠️ diagnostic snippet save failed:", e)

def cleanup_old_artifacts():
    """Removes files in LOGS_DIR older than LOG_RETENTION_DAYS."""
    if LOG_RETENTION_DAYS < 0:
        return
    
    print(f"🧹 Running log cleanup (Retention: {LOG_RETENTION_DAYS} days)...")
    now = time.time()
    cutoff = now - (LOG_RETENTION_DAYS * 86400)
    
    count = 0
    try:
        for filename in os.listdir(LOGS_DIR):
            file_path = os.path.join(LOGS_DIR, filename)
            if os.path.isfile(file_path):
                if os.path.getmtime(file_path) < cutoff:
                    os.remove(file_path)
                    count += 1
        if count > 0:
            print(f"   Done. Removed {count} old artifact(s).")
    except Exception as e:
        print(f"⚠️ Cleanup failed: {e}")

# --------------------------
# Login → MyLowesLife → UKG (keeps your original flow)
# --------------------------
def login_to_portal():
    print("🔑 Authenticating with Lowe's Portal...")
    driver.get("https://www.myloweslife.com")
    
    # 1. Wait for Portal Load
    try:
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "idToken2")))
    except Exception:
        if "Home" in driver.title or "MyLowesLife" in driver.page_source:
             print("✅ System: Session authenticated.")
             return True
        debug_dump("login_portal_timeout")
        raise Exception("Timed out waiting for initial login page.")

    # 2. Enter Credentials
    try:
        print("   -> Entering credentials...")
        driver.find_element(By.ID, "idToken1").send_keys(USERNAME)
        driver.find_element(By.ID, "idToken2").send_keys(PASSWORD)
        
        # Use robust JS click fallback
        login_btn = driver.find_element(By.ID, "loginButton_0")
        try:
            login_btn.click()
        except:
            js_click(login_btn)
        
        # 3. Transition to PIN
        print("   -> Authentication stage 1 submitted. Waiting for PIN prompt...")
        WebDriverWait(driver, 30).until(EC.invisibility_of_element_located((By.ID, "idToken2")))
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "idToken1")))
        
        # 4. Enter PIN
        print("   -> Entering security PIN...")
        driver.find_element(By.ID, "idToken1").send_keys(PIN)
        
        final_btn = driver.find_element(By.ID, "loginButton_0")
        try:
            final_btn.click()
        except:
            js_click(final_btn)
        
        time.sleep(3)
        print("✅ System: Portal authentication successful.")
        return True
    except Exception as e:
        debug_dump("login_failure")
        raise Exception(f"Login failed: {str(e)}")

# Utility to open the UKG tile if needed (kept for fallback)
def open_ukg_tile():
    def try_here():
        x1 = "//span[@class='toolname' and normalize-space()='UKG']"
        x2 = "//span[contains(@class,'toolname') and contains(normalize-space(),'UKG')]"
        x3 = "//img[contains(@src,'UKG-Avatar-social')]/ancestor::*[self::a or self::button or @role='button'][1]"
        for xp in (x1, x2):
            try:
                span = WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.XPATH, xp)))
                try:
                    clickable = span.find_element(By.XPATH, "ancestor::*[self::a or self::button or @role='button'][1]")
                except:
                    clickable = span
                old = driver.window_handles[:]
                js_click(clickable)
                switch_to_new_window(old, timeout=8)
                return True
            except Exception:
                pass
        try:
            card = WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.XPATH, x3)))
            old = driver.window_handles[:]
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

# small sleep then direct navigate to the Kronos URL (skip clicking tiles)
time.sleep(1)
try:
    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
except Exception:
    pass

# --------------------------
# Helpers
# --------------------------
TIME_RANGE_RX = re.compile(r"(\d{1,2}:\d{2}\s*(?:am|pm))\s*[-–]\s*(\d{1,2}:\d{2}\s*(?:am|pm))", re.IGNORECASE)

def click_next_and_wait_change():
    def grab_label():
        try:
            el = driver.find_element(By.CSS_SELECTOR, "[role='grid']")
            return el.get_attribute("outerText")[:80]
        except:
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
    """
    Robust parser:
     - Prefer DOM-sourced column->ISO mapping via JS.
     - If missing, use header td data-date or header day numbers + displayed month, but detect fc-other-month.
     - Last resort: constrained generic scan.
     - Always normalize and dedupe events.
    """
    soup = BeautifulSoup(view_html, "html.parser")
    events = []
    seen = set()

    def add_event_if_new(start_dt, end_dt):
        # normalize to minute resolution and dedupe
        start_dt = start_dt.replace(second=0, microsecond=0)
        end_dt   = end_dt.replace(second=0, microsecond=0)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
        key = (start_dt.isoformat(), end_dt.isoformat())
        if key in seen:
            return
        seen.add(key)
        events.append((start_dt, end_dt, "Lowe's 🛠️"))

    # Helpers
    def parse_dt(date_iso, time_str):
        for fmt in ("%Y-%m-%d %I:%M %p", "%Y-%m-%d %I:%M%p"):
            try:
                dt = datetime.strptime(f"{date_iso} {time_str}", fmt)
                # Localize to User's TZ immediately
                return arrow.get(dt, TZ)
            except:
                continue
        return None

    # 1) Try to get column->date mapping from live DOM (JS) — most reliable.
    col_to_date = {}
    try:
        js = """
        (function(){
          var out=[];
          var ths = document.querySelectorAll('table thead tr td');
          if(!ths || ths.length===0){
            // FullCalendar v5/6 day headers may be divs
            ths = document.querySelectorAll('.fc-daygrid-day'); 
          }
          ths.forEach(function(td){
            var d = td.getAttribute('data-date') || td.dataset && td.dataset.date || null;
            var other = td.className || '';
            var text = td.innerText||td.textContent||'';
            out.push({date:d, cls: other, text: text.trim()});
          });
          return out;
        })();
        """
        cols = driver.execute_script(js)
        if cols and isinstance(cols, list):
            for i, c in enumerate(cols, start=1):
                if c.get("date") and re.match(r"^\d{4}-\d{2}-\d{2}$", c.get("date")):
                    col_to_date[i] = c.get("date")
                else:
                    # mark other info so we can try to resolve later
                    col_to_date[i] = {"text": c.get("text",""), "cls": c.get("cls","")}
    except Exception:
        col_to_date = {}

    # 2) If JS returned non-empty mapping where values are plain strings (ISO), convert to simple map
    pure_map = {}
    for k,v in list(col_to_date.items()):
        if isinstance(v, str):
            pure_map[k] = v
    if pure_map:
        col_to_date = pure_map

    # 3) If we don't have ISO mapping for all header columns, try to build from HTML header
    if not any(isinstance(v, str) for v in col_to_date.values()):
        header_row = soup.select_one("table thead tr")
        month_year = None
        # try common toolbar selectors for displayed month/year
        tb = soup.select_one("span.toolbar-text.element-title") or soup.select_one(".fc-toolbar h2") or soup.select_one(".fc-toolbar .fc-center h2")
        if tb:
            month_year = tb.get_text(strip=True)
            m = re.search(r"([A-Za-z]{3,9}\s+\d{4})", month_year)
            if m:
                month_year = m.group(1)
        # Build mapping from header tds
        if header_row:
            header_tds = header_row.find_all("td", recursive=False)
            for idx, td in enumerate(header_tds, start=1):
                d_attr = td.get("data-date")
                if d_attr and re.match(r"^\d{4}-\d{2}-\d{2}$", d_attr):
                    col_to_date[idx] = d_attr
                else:
                    # day number text (may belong to prev/next month)
                    txt = td.get_text(" ", strip=True)
                    m = re.match(r"^(\d{1,2})$", txt or "")
                    if m and month_year:
                        # try parse, but ensure we select the correct month by inspecting classes
                        try:
                            for fmt in ("%b %Y %d", "%B %Y %d"):
                                try:
                                    dt = datetime.strptime(f"{month_year} {int(m.group(1))}", fmt)
                                    col_to_date[idx] = dt.strftime("%Y-%m-%d")
                                    break
                                except:
                                    continue
                        except:
                            pass

    # 4) If we still don't have any mapping, leave col_to_date empty and parser will try other strategies
    # At this point col_to_date can be partial map of idx->ISO

    # Table-based parsing using col_to_date where available
    try:
        if col_to_date:
            body_rows = soup.select("table tbody tr")
            for r in body_rows:
                tds = r.find_all("td", recursive=False)
                for col_idx, td in enumerate(tds, start=1):
                    date_iso = col_to_date.get(col_idx)
                    # if date_iso is dict-like (text/cls), skip (we couldn't resolve to ISO)
                    if not date_iso or isinstance(date_iso, dict):
                        continue
                    # prefer fc-time spans, then any time-like text in cell
                    time_nodes = td.select("span.fc-time") + td.select(".fc-time") + td.select("div.time, span.time")
                    for sp in time_nodes:
                        timestr = sp.get_text(" ", strip=True)
                        m = TIME_RANGE_RX.search(timestr or "")
                        if m:
                            s,e = m.group(1).lower(), m.group(2).lower()
                            sdt = parse_dt(date_iso, s); edt = parse_dt(date_iso, e)
                            if sdt and edt:
                                add_event_if_new(sdt, edt)
                    # fallback: generic search inside TD cell text
                    if not time_nodes:
                        txt = td.get_text(" ", strip=True)
                        for m in TIME_RANGE_RX.finditer(txt or ""):
                            s,e = m.group(1).lower(), m.group(2).lower()
                            sdt = parse_dt(date_iso, s); edt = parse_dt(date_iso, e)
                            if sdt and edt:
                                add_event_if_new(sdt, edt)
            if events:
                dprint("parse: used table-based strategy (DOM header map)")
                return events
    except Exception as ex:
        dprint("parse table-based error:", ex)

    # Div/daygrid based strategy (if day containers with data-date)
    try:
        day_divs = soup.select("div.fc-daygrid-day, div.fc-day, div.fc-daygrid-day-frame")
        if day_divs:
            for day in day_divs:
                date_iso = day.get("data-date") or None
                if not date_iso:
                    # try aria-label / extract embedded date string
                    aria = day.get("aria-label") or ""
                    m = re.search(r"(\d{4}-\d{2}-\d{2})", aria)
                    if m:
                        date_iso = m.group(1)
                if not date_iso:
                    continue
                for ev in day.select(".fc-event, .fc-daygrid-event, .fc-list-item, .event"):
                    txt = ev.get_text(" ", strip=True)
                    m = TIME_RANGE_RX.search(txt or "")
                    if m:
                        s,e = m.group(1).lower(), m.group(2).lower()
                        sdt = parse_dt(date_iso, s); edt = parse_dt(date_iso, e)
                        if sdt and edt:
                            add_event_if_new(sdt, edt)
            if events:
                dprint("parse: used div-based daygrid strategy")
                return events
    except Exception as ex:
        dprint("parse div-based error:", ex)

    # Constrained generic scan: map each time-match only if we can find a clear nearby data-date ancestor
    try:
        for node in soup.find_all(string=TIME_RANGE_RX):
            timestr = node.strip()
            m = TIME_RANGE_RX.search(timestr)
            if not m:
                continue
            candidate_date = None
            parent = node.parent
            for up in range(6):
                if not parent:
                    break
                # check for data-date attribute
                try:
                    val = parent.get("data-date") if hasattr(parent, "get") else None
                    if val and re.match(r"^\d{4}-\d{2}-\d{2}$", val):
                        candidate_date = val
                        break
                except Exception:
                    pass
                # check for an ancestor td with data-date
                try:
                    td = parent.find_parent("td")
                    if td:
                        v = td.get("data-date")
                        if v and re.match(r"^\d{4}-\d{2}-\d{2}$", v):
                            candidate_date = v
                            break
                except:
                    pass
                parent = parent.parent
            if not candidate_date:
                continue
            s,e = m.group(1).lower(), m.group(2).lower()
            sdt = parse_dt(candidate_date, s); edt = parse_dt(candidate_date, e)
            if sdt and edt:
                add_event_if_new(sdt, edt)
        if events:
            dprint("parse: used constrained generic scan")
            return events
    except Exception as ex:
        dprint("parse generic-scan error:", ex)

    return events

def scrape_shifts_from_aside(max_clicks=None):
    found = []
    # primary selector for day cells
    tds = driver.find_elements(By.CSS_SELECTOR, "td[data-date]")
    if not tds:
        tds = driver.find_elements(By.CSS_SELECTOR, "div.fc-daygrid-day[data-date], div[data-date]")

    clicks = 0
    for td in tds:
        if max_clicks and clicks >= max_clicks:
            break
        date_iso = td.get_attribute("data-date")
        if not date_iso:
            continue
        clicks += 1
        try:
            # click the day number if present, else the cell
            try:
                daynum = td.find_element(By.CSS_SELECTOR, ".fc-day-number")
                js_click(daynum)
            except:
                js_click(td)
            # wait briefly for panel to fill
            panel_text = ""
            try:
                WebDriverWait(driver, 3).until(
                    lambda d: any(d.find_elements(By.CSS_SELECTOR, sel) for sel in (".employee-view-aside", ".aside", ".krn-list", ".panel-aside", ".side-panel", "aside"))
                )
            except:
                pass
            for sel in (".employee-view-aside", ".aside", ".krn-list", ".panel-aside", ".side-panel", "aside", ".shift-detail", ".shift-info"):
                try:
                    el = driver.find_element(By.CSS_SELECTOR, sel)
                    panel_text = (el.get_attribute("innerText") or "")
                    if panel_text.strip():
                        break
                except:
                    panel_text = ""
            if not panel_text:
                try:
                    right_col = driver.find_element(By.CSS_SELECTOR, ".right-column, .right-pane, .krn-panel, .panel-right")
                    panel_text = (right_col.get_attribute("innerText") or "")
                except:
                    panel_text = ""
            if not panel_text:
                continue
            for m in TIME_RANGE_RX.finditer(panel_text):
                start_s = m.group(1).lower()
                end_s   = m.group(2).lower()
                try:
                    sdt_naive = datetime.strptime(f"{date_iso} {start_s}", "%Y-%m-%d %I:%M %p")
                    edt_naive = datetime.strptime(f"{date_iso} {end_s}",   "%Y-%m-%d %I:%M %p")
                    
                    sdt = arrow.get(sdt_naive, TZ)
                    edt = arrow.get(edt_naive, TZ)
                    
                    if edt <= sdt:
                        edt = edt.shift(days=1)
                    found.append((sdt, edt, "Lowe's 🛠️"))
                except:
                    continue
        except Exception:
            dprint("aside scrape error:", traceback.format_exc())
            continue
        finally:
            time.sleep(0.12)
    return found

def run_scrape_cycle():
    # Navigate
    driver.get("https://lowescompanies-sso.prd.mykronos.com/ess#/")
    print("🡺 Navigated directly to schedule portal")

    # loose wait for calendar
    try:
        WebDriverWait(driver, 8).until(lambda d: d.find_elements(By.CSS_SELECTOR, "td[data-date], .fc-daygrid-day"))
        # Extra robustness: wait for at least one event to appear if possible
        try:
            WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".fc-event, .fc-daygrid-event, .event")))
            time.sleep(1.0) # settle
        except:
            print("⚠️ No events appeared within 5s (might be empty schedule).")
    except Exception:
        pass

    diagnostic_calendar_snapshot("before_save")
    time.sleep(0.9)
    # Combined Crawl Strategy: Grid → Aside Fallback per page
    found_events = []
    
    # Walk through up to 3 pages (covers Current, Next, and Next-Next months/periods)
    for i in range(1, 4):
        page_tag = f"p{i}"
        dprint(f"--- Crawling Page {i} ---")
        
        # 1. Capture HTML for grid parsing
        current_html = save_view(f"my_schedule_{page_tag}")
        
        # 2. Try Grid Parsing
        grid_events = parse_fullcalendar_period(current_html)
        if grid_events:
            print(f"🧩 Page {i}: Found {len(grid_events)} event(s) via Grid parser.")
            found_events.extend(grid_events)
        else:
            print(f"⚠️ Page {i}: Grid parser found 0 events. Attempting Aside Crawler...")
            # If grid fails (List view or rendering delay), try the robust aside crawler
            # This only scrapes the days visible in the current view
            aside_events = scrape_shifts_from_aside()
            if aside_events:
                print(f"🧩 Page {i}: Found {len(aside_events)} event(s) via Aside Crawler.")
                found_events.extend(aside_events)
            else:
                print(f"⚠️ Page {i}: Both parsers found 0 events.")
        
        # 3. Move to next page
        if i < 3: # don't click next on the last allowed page
            if click_next_and_wait_change():
                dprint(f"Successfully navigated to page {i+1}")
                time.sleep(1.0) # wait for render
            else:
                dprint(f"Pagination stop: Next button not found or view did not change at page {i}.")
                break
    
    # De-dupe and Sort
    # events are tuples: (start_dt, end_dt, label)
    final_events = sorted(set(found_events), key=lambda x: (x[0], x[1]))
    return final_events

# --------------------------
# Google Calendar sync
# --------------------------
def get_calendar_service():
    creds = None
    # Use global CONFIG_DIR ("data") for persistence in Docker
    TOKEN_PATH = os.path.join(CONFIG_DIR, "token.json")
    CREDENTIALS_PATH = os.path.join(CONFIG_DIR, "credentials.json")

    if not os.path.exists(CREDENTIALS_PATH):
        # Extremely robust environment check for headless deployment
        env_keys = {k.upper(): v for k, v in os.environ.items()}
        
        cid_key = "GOOGLE_CLIENT_ID"
        sec_key = "GOOGLE_CLIENT_SECRET"
        
        env_cid = env_keys.get(cid_key)
        env_csec = env_keys.get(sec_key)
        
        if env_cid and env_csec:
            # Strip quotes and whitespace
            env_cid = env_cid.strip().strip('"').strip("'")
            env_csec = env_csec.strip().strip('"').strip("'")
            
            print(f"🔹 Authenticating with Google Credentials from environment...", flush=True)
            data = {"installed":{"client_id":env_cid,"project_id":"lowes-scheduler","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_secret":env_csec,"redirect_uris":["http://localhost"]}}
            try:
                with open(CREDENTIALS_PATH, "w") as f:
                    json.dump(data, f)
                print("✅ Service credentials generated from environment.", flush=True)
            except Exception as e:
                print(f"❌ Failed to initialize credentials: {e}", flush=True)
        else:
            # Fallback to interactive ONLY if we are in a terminal
            if sys.stdin.isatty():
                print("\nℹ️ Setup: Manual Google Calendar authorization required.", flush=True)
                print("1. Navigate to: https://console.cloud.google.com/apis/credentials", flush=True)
                print("2. Obtain OAuth 2.0 Client ID (Desktop App).", flush=True)
                try:
                    cid = input("Enter Client ID: ").strip()
                    csec = input("Enter Client Secret: ").strip()
                    if cid and csec:
                        data = {"installed":{"client_id":cid,"project_id":"lowes-scheduler","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_secret":csec,"redirect_uris":["http://localhost"]}}
                        with open(CREDENTIALS_PATH, "w") as f:
                            json.dump(data, f)
                        print("✅ Credentials saved locally.", flush=True)
                except (EOFError, KeyboardInterrupt):
                    print("🛑 Setup interrupted. Synchronization aborted.", flush=True)
                    return None
            else:
                # ONLY PRINT IF MISSING
                print(f"\n❌ CRITICAL ERROR: Google Credentials (GOOGLE_CLIENT_ID/SECRET) not provided.", flush=True)
                print("➡️ Please verify your environment configuration in your service manager or container environment.", flush=True)
                return None

    if not os.path.exists(TOKEN_PATH):
        # Support injecting the authorized token via environment variable for headless setups
        env_token = (os.getenv("GOOGLE_TOKEN_JSON") or "").strip().strip('"').strip("'")
        if env_token:
            print("🔹 Initializing Google Token from environment...", flush=True)
            try:
                # Validate JSON before writing
                token_data = json.loads(env_token)
                with open(TOKEN_PATH, "w") as f:
                    json.dump(token_data, f)
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
                try: os.remove(TOKEN_PATH)
                except: pass
                creds = None
        if not creds or not creds.valid:
            print("🔑 Opening browser for reauthorization...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
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

    # Dynamic Sync Window: 
    # To avoid deleting history we didn't scrape, we only sync from the earliest parsed shift.
    # We add a 24-hour buffer to catch immediate schedule changes.
    earliest_parsed = min(ev.begin for ev in cal.events)
    time_min = earliest_parsed.shift(hours=-24).isoformat()
    # Looking forward 90 days is safe.
    time_max = earliest_parsed.shift(days=90).isoformat()

    all_events_g = service.events().list(
        calendarId=calendar_id,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime"
    ).execute().get("items", [])

    lowes_events = [e for e in all_events_g if e.get("summary") == "Lowe's 🛠️"]
    
    # Smart Sync Logic:
    # 1. Map existing events by (start, end)
    # 2. Map parsed events by (start, end)
    # 3. Delete events in GCal that are NOT in parsed list
    # 4. Add events in parsed list that are NOT in GCal

    g_map = {}
    for e in lowes_events:
        st = e["start"].get("dateTime") or e["start"].get("date")
        et = e["end"].get("dateTime") or e["end"].get("date")
        if st and et:
            # Shift to UTC for robust comparison
            s_utc = arrow.get(st).to('UTC').format("YYYY-MM-DDTHH:mm:ss")
            e_utc = arrow.get(et).to('UTC').format("YYYY-MM-DDTHH:mm:ss")
            g_map[(s_utc, e_utc)] = e["id"]

    p_map = {}
    for ev in cal.events:
        # ev.begin/end are already localized arrow objects
        s_utc = ev.begin.to('UTC').format("YYYY-MM-DDTHH:mm:ss")
        e_utc = ev.end.to('UTC').format("YYYY-MM-DDTHH:mm:ss")
        p_map[(s_utc, e_utc)] = ev

    deleted_dates = set()
    for (s, en), eid in g_map.items():
        if (s, en) not in p_map:
            try:
                service.events().delete(calendarId=calendar_id, eventId=eid).execute()
                deleted_dates.add(s[:10])
                print(f"🗑️ Deleted stale shift on {s[:10]} {s[11:]}")
            except Exception as e:
                print(f"❌ Failed to delete: {e}")

    added_dates = set()
    for (s_utc, e_utc), ev in p_map.items():
        if (s_utc, e_utc) not in g_map:
            try:
                # Convert back to local for the actual insert
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

    changed_dates = sorted(added_dates.union(deleted_dates))
    if changed_dates:
        changes = []
        for d in changed_dates:
            if d in deleted_dates and d in added_dates:
                changes.append(f"🔁 Updated shift on {d}")
            elif d in deleted_dates:
                changes.append(f"❌ Removed shift on {d}")
            elif d in added_dates:
                changes.append(f"➕ New shift on {d}")
        send_discord_update(changes)
    else:
        print("✅ No calendar changes; no Discord notification.")

def main_task():
    print(f"\n--- Synchronization Process Initiated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
    
    # Automated cleanup
    cleanup_old_artifacts()

    # Ensure logged in
    try:
        login_to_portal()
    except Exception as e:
        print(f"❌ Login failed: {e}")
        return

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

    # Build ICS
    calendar = Calendar()
    for start_dt, end_dt, label in all_events:
        ev = Event()
        ev.name = label
        ev.begin = start_dt
        ev.end   = end_dt
        calendar.events.add(ev)

    print(f"✅ Parsed {len(all_events)} shift(s).")

    ics_name = os.path.join(LOGS_DIR, f"schedule_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.ics")
    with open(ics_name, "w", encoding="utf-8") as f:
        f.write(str(calendar))
    print(f"🗂️ Calendar saved as {ics_name}")

    # Do sync
    sync_to_google_calendar(calendar)
    print(f"💤 Job finished at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


# --------------------------
# Scheduler / Entry Point
# --------------------------
if __name__ == "__main__":
    print(f"Lowe's Schedule Synchronization Service - {VERSION}")
    if RUN_MODE == "once":
        main_task()
        print("Synchronization completed successfully. Exiting.")
        driver.quit()
    else:
        print(f"Schedule synchronization active: {RUN_MODE} {RUN_VALUE}")
        
        main_task()

        if RUN_MODE == "daily":
            # RUN_VALUE should be HH:MM
            schedule.every().day.at(RUN_VALUE).do(main_task)
            print(f"Next synchronization scheduled for {RUN_VALUE}")
        elif RUN_MODE == "interval":
            # RUN_VALUE is hours int
            try:
                h = int(RUN_VALUE)
                schedule.every(h).hours.do(main_task)
                print(f"Service running on a {h}-hour interval.")
            except:
                print("❌ Configuration Error: Invalid interval value.")
                driver.quit()
                sys.exit(1)
        
        print("System monitoring active. Waiting for scheduled tasks...")
        
        last_heartbeat = time.time()
        try:
            while True:
                schedule.run_pending()
                
                # Heartbeat every 10 minutes to verify process health in logs
                if time.time() - last_heartbeat > 600:
                    print(f"💓 Service Heartbeat: System active at {datetime.now().strftime('%H:%M:%S')}")
                    last_heartbeat = time.time()
                    
                time.sleep(10)
        except Exception as e:
            print(f"❌ Critical error in scheduler loop: {e}", flush=True)
            traceback.print_exc()
        finally:
            print("🔻 Service is terminating.", flush=True)
            driver.quit()
