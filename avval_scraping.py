from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import mysql.connector
import logging
import json
import time
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ----------------- Database -----------------
def connect_to_database():
    try:
        data = mysql.connector.connect(
            host='localhost',
            user='root',
            port=3307,
            password='',
            database='scraping_data'
        )
        cursor = data.cursor()
        logging.info("✅ Connected to database successfully.")
        return data, cursor
    except mysql.connector.Error as err:
        logging.error(f"❌ Database connection error: {err}")
        return None, None

def load_existing_phones(cursor):
    """Load all existing phone numbers from database into a set"""
    existing = set()
    cursor.execute("SELECT phone_number FROM data WHERE phone_number IS NOT NULL AND phone_number != ''")
    for (phone,) in cursor.fetchall():
        existing.add(phone.strip())
    logging.info(f"📱 Loaded {len(existing)} existing phone numbers from database.")
    return existing

def save_to_database(data, existing_phones, cursor, conn):
    """
    data = [name, specialty, phone_number, address, email, category, gis_json]
    """
    phone_number = data[2]
    if phone_number in existing_phones:
        logging.info(f"⚠️ Duplicate phone skipped: {phone_number}")
        return

    try:
        sql = """
            INSERT INTO data
            (name, specialty, phone_number, address, email, category, gis)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(sql, data)
        conn.commit()
        existing_phones.add(phone_number)
        logging.info(f"💾 Saved to database: {data}")
    except mysql.connector.Error as err:
        logging.error(f"❌ Database error: {err}")
        conn.rollback()

# ----------------- GIS Extraction -----------------
def extract_gis_from_card(card):
    try:
        map_link = card.find_element(By.XPATH, '//*[@id="search_form"]/div[1]/main/div[3]/div[1]/div[2]/a[2]').get_attribute('href')
        match = re.search(r'destination=([0-9.\-]+),([0-9.\-]+)', map_link)
        if match:
            lat, lon = match.groups()
            gis_json = json.dumps({"lat": float(lat), "lon": float(lon)}, ensure_ascii=False)
        else:
            gis_json = json.dumps({"lat": None, "lon": None}, ensure_ascii=False)
    except:
        gis_json = json.dumps({"lat": None, "lon": None}, ensure_ascii=False)
    return gis_json

# ----------------- Browser setup -----------------
def run_avval(start_url="https://avval.ir/"):
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        logging.info("✅ Browser opened successfully.")
    except Exception as e:
        logging.error(f"❌ Failed to start browser: {e}")
        return

    driver.get(start_url)
    logging.info(f"🌐 Opened start URL: {start_url}")

    # ----------------- Helper -----------------
    def get_text_safe(xpath, parent):
        try:
            el = parent.find_element(By.XPATH, xpath)
            return el.text.strip()
        except:
            return ""

    def get_texts_safe(xpath, parent):
        try:
            els = parent.find_elements(By.XPATH, xpath)
            return ', '.join([el.text.strip() for el in els if el.text.strip()])
        except:
            return ""

    # ----------------- Extract data -----------------
    def extract_data_from_page():
        try:
            cards = WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.XPATH, '//div[@class="content"]'))
            )
            logging.info(f"📦 Found {len(cards)} cards on this page.")
        except TimeoutException:
            logging.warning("⚠️ No cards found!")
            return False

        duplicate_count = 0  # شمارنده‌ی شماره‌های تکراری

        for card in cards:
            name = get_text_safe('.//h2/a', card)
            specialty = get_text_safe('.//div[contains(@class,"keywords")]', card)
            phone_number = get_texts_safe('.//div[@data-print-adv="phone"]/span', card)
            address = get_text_safe('.//p[@data-print-adv="address"]', card)
            email = get_text_safe('.//div[@data-print-adv="email"]/span', card)
            category = get_text_safe('//h1', driver)
            gis_json = extract_gis_from_card(card)

            # بررسی تکراری بودن
            if phone_number in existing_phones:
                duplicate_count += 1
                logging.info(f"⚠️ Duplicate phone found ({duplicate_count}/5): {phone_number}")
                if duplicate_count > 5:
                    logging.warning("🚫 More than 5 duplicates on this page, skipping category...")
                    return True
                continue

            data_to_save = [name, specialty, phone_number, address, email, category, gis_json]
            save_to_database(data_to_save, existing_phones, cursor, conn)
            logging.info(f"🟢 Extracted: {name} | {specialty} | {phone_number} | {address} | {email} | {category} | {gis_json}")

        return False  # ادامه بده

    # ----------------- Pagination -----------------
    def go_next_page():
        try:
            next_btn = driver.find_element(By.XPATH, '//ul[@class="pagination"]/li/a[contains(text(),"»")]')
            driver.execute_script("arguments[0].click();", next_btn)
            time.sleep(2)
            logging.info("➡ Moved to next page.")
            return True
        except NoSuchElementException:
            logging.info("ℹ️ No next page button.")
            return False
        except Exception as e:
            logging.warning(f"⚠️ Cannot go to next page: {e}")
            return False

    # ----------------- Loop through categories -----------------
    try:
        categories = WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.XPATH, '//*[@id="directory"]/div[1]//a'))
        )
        logging.info(f"📚 Found {len(categories)} categories.")
    except TimeoutException:
        logging.error("❌ Categories not found!")
        driver.quit()
        return

    category_links = [cat.get_attribute("href") for cat in categories if cat.get_attribute("href")]

    for i, link in enumerate(category_links):
        driver.get(link)
        time.sleep(2)
        logging.info(f"➡ Entered category: {link}")

        while True:
            skip_category = extract_data_from_page()
            if skip_category:
                logging.info("⏭ Skipping to next category due to too many duplicates.")
                break
            if not go_next_page():
                break

        if (i + 1) % 5 == 0:
            logging.info("💤 Short break to avoid blocking...")
            time.sleep(5)

    driver.quit()
    logging.info("✅ Scraping completed.")

# ----------------- Main -----------------
if __name__ == "__main__":
    conn, cursor = connect_to_database()
    if conn is None:
        exit()

    # 🔹 Load existing phones before start
    existing_phones = load_existing_phones(cursor)

    start_url = input("🌐 Enter start URL (default https://avval.ir/): ").strip()
    if not start_url:
        start_url = "https://avval.ir/"
    run_avval(start_url)
