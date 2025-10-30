import os
import time
import sqlite3
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask, jsonify, render_template
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from contextlib import contextmanager
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import re
from flask_cors import CORS
from dotenv import load_dotenv

flask_app = Flask(__name__, template_folder='web_app/templates')
flask_app.config['CORS_HEADERS'] = 'Content-Type'
CORS(flask_app)
load_dotenv()

LOGIN_URL = "https://res.isdc.co.kr/login.do"
FACILITY_CODES = ["FAC101", "FAC61", "FAC58", "FAC95", "FAC99", "FAC78", "FAC18", "FAC53"]
FACILITY_NAMES = {"FAC101": "구미", "FAC61": "수내", "FAC58": "대원", "FAC95": "태평", "FAC99": "야탑", "FAC78": "양지", "FAC18": "탄천", "FAC53": "희망대"}
DB_PATH = '/home/ubuntu/tennis_courts.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS availability (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        facility TEXT,
        date TEXT,
        court TEXT,
        time TEXT,
        popular INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS last_scan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        last_scan TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

@flask_app.route('/api/availability')
def get_availability():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT timestamp, facility, date, court, time, popular FROM availability WHERE timestamp >= ? ORDER BY timestamp DESC",
                  ((datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S'),))
        results = c.fetchall()
        data = [dict(row) for row in results]
        c.execute("SELECT last_scan FROM last_scan ORDER BY last_scan DESC LIMIT 1")
        last_scan = c.fetchone()
        if last_scan:
            data = [{'last_scan': last_scan['last_scan'], **row} for row in data]
        else:
            data = [{'last_scan': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), **row} for row in data]
        conn.close()
        return jsonify(data)
    except sqlite3.Error as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] API Database error: {e}")
        return jsonify({"error": "Database error occurred"}), 500

@flask_app.route('/')
def show_availability_html():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT timestamp, facility, date, court, time, popular FROM availability WHERE timestamp >= ? ORDER BY timestamp DESC",
                  ((datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S'),))
        results = c.fetchall()
        c.execute("SELECT last_scan FROM last_scan ORDER BY last_scan DESC LIMIT 1")
        last_scan = c.fetchone()
        last_updated = last_scan['last_scan'] if last_scan else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.close()
        return render_template('index.html', results=results, last_updated=last_updated)
    except sqlite3.Error as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] HTML Database error: {e}")
        return render_template('index.html', results=[], last_updated="Error")

@contextmanager
def get_driver():
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(options=options, service=Service(ChromeDriverManager().install()))
    try:
        yield driver
    finally:
        driver.quit()

def send_telegram_notification(message, context=None):
    if context:
        context.bot.send_message(chat_id=os.getenv("TELEGRAM_CHAT_ID"), text=message)
    else:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not bot_token or not chat_id:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Telegram credentials not set. Message: {message}")
            return
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        try:
            response = requests.post(url, data={"chat_id": chat_id, "text": message}, timeout=10)
            if response.status_code != 200:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Telegram error: {response.text}")
            else:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Telegram notification sent: {message[:50]}...")
        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Telegram request failed: {str(e)}")

def check_tennis_court_availability(context=None):
    check_dates = [
        datetime.now().date().strftime("%Y-%m-%d"),
        (datetime.now().date() + timedelta(days=1)).strftime("%Y-%m-%d"),
        (datetime.now().date() + timedelta(days=2)).strftime("%Y-%m-%d"),
        (datetime.now().date() + timedelta(days=3)).strftime("%Y-%m-%d")
    ]
    available_slots = []
    with get_driver() as driver:
        wait = WebDriverWait(driver, 10)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting login...")
        driver.get("https://res.isdc.co.kr/login.do")
        username = os.getenv("TENNIS_USERNAME")
        password = os.getenv("TENNIS_PASSWORD")
        if not username or not password:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Error: Login credentials missing.")
            send_telegram_notification("Error: Login credentials missing.", context)
            return available_slots
        try:
            wait.until(EC.presence_of_element_located((By.ID, "web_id"))).send_keys(username)
            wait.until(EC.presence_of_element_located((By.ID, "web_pw"))).send_keys(password)
            wait.until(EC.presence_of_element_located((By.ID, "btn_login"))).click()
            wait.until(EC.url_contains("index.do"))
        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Login failed: {str(e)}")
            send_telegram_notification(f"Login failed: {str(e)}", context)
            return available_slots
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('DELETE FROM availability')
        c.execute('DELETE FROM last_scan')
        current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute('INSERT INTO last_scan (last_scan) VALUES (?)', (current_timestamp,))
        for fac_code in FACILITY_CODES:
            fac_name = FACILITY_NAMES[fac_code]
            for date in check_dates:
                url = f"https://res.isdc.co.kr/otherTimetable.do?facId={fac_code}&resdate={date}"
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checking {fac_name} on {date}")
                driver.get(url)
                wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                slots = driver.find_elements(By.XPATH, "//button[contains(text(), '예약가능') and contains(@class, 'timeSel')]")
                if not slots:
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] No '예약가능' buttons found for {fac_name} on {date}")
                for slot in slots:
                    try:
                        time_element = slot.find_element(By.XPATH, "./ancestor::tr/td[contains(@class, 'td-title') and position()=3]").text.strip()
                        table = slot.find_element(By.XPATH, "./ancestor::table")
                        table_box = table.find_element(By.XPATH, "./ancestor::div[contains(@class, 'tableBox')]")
                        label_element = table_box.find_element(By.XPATH, "./preceding-sibling::label[contains(@class, 'lb-timetable')][1]")
                        facility_date = label_element.text.strip()
                        # Use facility from URL instead of label
                        facility_short = fac_name
                        court_number = None
                        if "번" in facility_date:
                            court_number_part = facility_date.split("번")[0].split()[-1]
                            court_number = court_number_part if court_number_part.isdigit() else None
                        if not court_number and re.search(r'\((\d+)번\)', facility_date):
                            court_number_match = re.search(r'\((\d+)번\)', facility_date)
                            court_number = court_number_match.group(1) if court_number_match else None
                        court_number = court_number if court_number and court_number.isdigit() else "Unknown"
                        date_match = re.search(r'\((\d{4}-\d{2}-\d{2})\)', facility_date)
                        date_full = date_match.group(1) if date_match else date
                        date_short = date_full[5:] if len(date_full.split("-")) > 1 else date
                        # Check for popular times
                        scan_date = datetime.strptime(date_full, '%Y-%m-%d')
                        is_weekend = scan_date.weekday() in [5, 6]  # Saturday (5), Sunday (6)
                        time_hour = int(time_element.split(':')[0])  # Assuming 24-hour format
                        is_after_6pm = time_hour >= 18
                        popular = 1 if is_weekend or is_after_6pm else 0
                        if court_number != "Unknown" and "간표" not in facility_short:
                            slot_info = f"{facility_short} - {date_short} - Court {court_number} at {time_element}"
                            available_slots.append(slot_info)
                            c.execute("INSERT INTO availability (timestamp, facility, date, court, time, popular) VALUES (?, ?, ?, ?, ?, ?)",
                                      (current_timestamp, facility_short, date_short, court_number, time_element, popular))
                            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Found: {slot_info} (Popular: {popular})")
                    except Exception as e:
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Error extracting slot: {str(e)}")
                        court_number_fallback = "99"  # Changed from "1" to "99"
                        slot_info = f"{fac_name} - {date_short} - Court {court_number_fallback} at {time_element}"
                        available_slots.append(slot_info)
                        c.execute("INSERT INTO availability (timestamp, facility, date, court, time, popular) VALUES (?, ?, ?, ?, ?, ?)",
                                  (current_timestamp, fac_name, date_short, court_number_fallback, time_element, popular))
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Found (fallback): {slot_info} (Popular: {popular})")
                    continue
                time.sleep(0.1)
        conn.commit()
        conn.close()
        # === PUSH DB TO WEB FOLDER (for Render) ===
        shutil.copy(DB_PATH, "/home/ubuntu/tennis_bot/web_app/tennis_courts.db")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DB copied to web_app folder")
        # === AUTO-PUSH TO GITHUB ===
        subprocess.run(["/home/ubuntu/push_to_github.sh"])
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Pushed to GitHub")
        # === RESTART FLASK SERVER ===
        subprocess.run(["/home/ubuntu/restart_flask.sh"])
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Flask server restarted")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scan completed")
        return available_slots

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Received /scan command from {update.effective_user.name}")
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Starting tennis court scan...")
    available_slots = check_tennis_court_availability(context)
    message = "Tennis Court Availability Found:\n\n" + "\n".join(available_slots) if available_slots else "No availability found."
    if len(message) > 4096:
        for i in range(0, len(available_slots), 10):
            chunk = available_slots[i:i + 10]
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Tennis Court Availability Found:\n\n" + "\n".join(chunk))
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=message)
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Scan completed.")

def start_flask_server():
    context = ('/etc/letsencrypt/live/129.154.57.126/fullchain.pem', '/etc/letsencrypt/live/129.154.57.126/privkey.pem')
    flask_app.run(host='0.0.0.0', port=5000)
if __name__ == "__main__":
    flask_thread = Thread(target=start_flask_server, daemon=True)
    flask_thread.start()
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Telegram bot token not set. Exiting.")
        exit(1)
    application = Application.builder().token(bot_token).build()
    application.add_handler(CommandHandler("scan", scan_command))
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Bot and web server are running. Send /scan to trigger a scan. Visit http://129.154.57.126:5000/")
    application.run_polling()