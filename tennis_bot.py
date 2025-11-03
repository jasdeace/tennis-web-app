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
CORS(flask_app)
load_dotenv()

LOGIN_URL = "https://res.isdc.co.kr/login.do"
FACILITY_CODES = ["FAC101", "FAC61", "FAC58", "FAC95", "FAC99", "FAC78", "FAC18"]
FACILITY_NAMES = {"FAC101": "구미", "FAC61": "수내", "FAC58": "대원", "FAC95": "태평", "FAC99": "야탑", "FAC78": "양지", "FAC18": "탄천"}
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
        time TEXT
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
        c.execute("SELECT timestamp, facility, date, court, time FROM availability ORDER BY timestamp DESC")
        results = c.fetchall()
        data = [dict(row) for row in results]
        conn.close()
        return jsonify(data)
    except Exception as e:
        print(f"API error: {e}")
        return jsonify({"error": str(e)}), 500

@flask_app.route('/')
def index():
    return render_template('index.html')

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

def check_tennis_court_availability():
    check_dates = [
        datetime.now().date().strftime("%Y-%m-%d"),
        (datetime.now().date() + timedelta(days=1)).strftime("%Y-%m-%d"),
        (datetime.now().date() + timedelta(days=2)).strftime("%Y-%m-%d"),
        (datetime.now().date() + timedelta(days=3)).strftime("%Y-%m-%d")
    ]
    available_slots = []
    with get_driver() as driver:
        wait = WebDriverWait(driver, 10)
        driver.get(LOGIN_URL)
        username = os.getenv("TENNIS_USERNAME")
        password = os.getenv("TENNIS_PASSWORD")
        wait.until(EC.presence_of_element_located((By.ID, "web_id"))).send_keys(username)
        wait.until(EC.presence_of_element_located((By.ID, "web_pw"))).send_keys(password)
        wait.until(EC.presence_of_element_located((By.ID, "btn_login"))).click()
        wait.until(EC.url_contains("index.do"))

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('DELETE FROM availability')
        current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for fac_code in FACILITY_CODES:
            fac_name = FACILITY_NAMES[fac_code]
            for date in check_dates:
                url = f"https://res.isdc.co.kr/otherTimetable.do?facId={fac_code}&resdate={date}"
                driver.get(url)
                wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                slots = driver.find_elements(By.XPATH, "//button[contains(text(), '예약가능') and contains(@class, 'timeSel')]")
                for slot in slots:
                    try:
                        time_element = slot.find_element(By.XPATH, "./ancestor::tr/td[contains(@class, 'td-title') and position()=3]").text.strip()
                        table = slot.find_element(By.XPATH, "./ancestor::table")
                        table_box = table.find_element(By.XPATH, "./ancestor::div[contains(@class, 'tableBox')]")
                        label_element = table_box.find_element(By.XPATH, "./preceding-sibling::label[contains(@class, 'lb-timetable')][1]")
                        facility_date = label_element.text.strip()
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
                        if court_number != "Unknown":
                            slot_info = f"{fac_name} - {date_short} - Court {court_number} at {time_element}"
                            available_slots.append(slot_info)
                            c.execute("INSERT INTO availability (timestamp, facility, date, court, time) VALUES (?, ?, ?, ?, ?)",
                                      (current_timestamp, fac_name, date_short, court_number, time_element))
                    except Exception as e:
                        print(f"Error: {e}")
                        continue
                time.sleep(0.1)
        conn.commit()
        conn.close()
        return available_slots

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Scanning...")
    slots = check_tennis_court_availability()
    message = "\n".join(slots) if slots else "No availability"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=message)

def start_flask_server():
    flask_app.run(host='0.0.0.0', port=5000)

if __name__ == "__main__":
    flask_thread = Thread(target=start_flask_server, daemon=True)
    flask_thread.start()
    application = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    application.add_handler(CommandHandler("scan", scan_command))
    application.run_polling()