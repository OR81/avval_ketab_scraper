import json
import logging
import os
import re
import time

import pymysql
from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import ElementClickInterceptedException, NoSuchElementException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables
load_dotenv()

# ----------------- Database setup -----------------
conn = pymysql.connect(host=os.getenv('DB_HOST', 'localhost'), user=os.getenv('DB_USER', 'root'),
                       password=os.getenv('DB_PASSWORD', ''), port=int(os.getenv('DB_PORT', 3307)),
                       database=os.getenv('DB_NAME', 'scraping_data'), charset='utf8mb4',
                       cursorclass=pymysql.cursors.DictCursor)
cursor = conn.cursor()


def save_to_database(data):
    try:
        sql = """
              INSERT INTO avval_data
              (name, specialty, phone_number, address, email, category, subcategory, subsidiary, gis)
              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
              """
        cursor.execute(sql, tuple(data))
        conn.commit()
        # logging.info(f"💾 Saved: {data[0]}")
    except Exception as e:
        # logging.error(f"❌ DB error: {e}")
        conn.rollback()


# ----------------- Browser setup -----------------
chrome_options = Options()
debug_mode = os.getenv('DEBUG', 'false').lower() == 'true'
if not debug_mode:
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-features=VizDisplayCompositor")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--disable-background-timer-throttling")
    chrome_options.add_argument("--disable-renderer-backgrounding")
    chrome_options.add_argument("--disable-backgrounding-occluded-windows")

chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-extensions")
chrome_options.add_argument("--window-size=1280,1024")

service = Service("bin/chromedriver")  # مسیر کروم درایور خود را چک کنید
driver = webdriver.Chrome(service=service, options=chrome_options)
wait = WebDriverWait(driver, 10)

start_url = "https://avval.ir/"
driver.get(start_url)


# ----------------- Helper Functions -----------------
def scroll_click(element):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        time.sleep(0.4)
        element.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", element)


def get_element_text_safe(card, el):
    try:
        element = card.find_element(By.XPATH, el)
        return element.text.strip()
    except:
        return "NoTextFound."


def get_text_safe(el):
    try:
        return el.text.strip()
    except:
        return "NoTextFound."


def load_existing_phones(cursor):
    existing = set()

    cursor.execute("""
                   SELECT phone_number
                   FROM avval_data
                   WHERE phone_number IS NOT NULL
                     AND phone_number != ''
                   """)

    for row in cursor.fetchall():
        phones = row['phone_number']
        existing.add(phones)

    # logging.info(f"📱 Loaded {len(existing)} existing phone numbers from database.")

    return tuple(existing)


def clean_sub_name(full_text):
    text = full_text.strip()
    text = text.replace("بهترین", "").strip()
    if "در" in text:
        text = text.split("در")[0].strip()
    return text


def expand_phone_range(phone: str):
    # حذف فاصله و خط تیره
    phone = phone.replace("-", "").replace(" ", "")

    # اگر محدوده وجود ندارد، شماره را همانطور بازگردان
    if "~" not in phone:
        return [phone]

    base, end_suffix = phone.split("~")

    # تعداد ارقام پایانی برای شروع
    start_suffix = base[-len(end_suffix):]
    prefix = base[:-len(end_suffix)]

    start = int(start_suffix)
    end = int(end_suffix) + start - int(start_suffix)  # محاسبه عدد واقعی پایانی

    return [f"{prefix}{i}" for i in range(start, end + 1)]


def wait_for_dropdown(driver, timeout=10):
    try:
        return WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.XPATH, "//div[contains(@class,'selectize-input')]")))
    except:
        return None


def extract_gis_from_card(card):
    try:
        link = card.find_element(By.XPATH, '//a[contains(@href,"destination=")]').get_attribute('href')
        m = re.search(r'destination=([0-9.\-]+),([0-9.\-]+)', link)
        if m:
            return json.dumps({"lat": float(m.group(1)), "lon": float(m.group(2))}, ensure_ascii=False)
    except:
        pass
    return json.dumps({"lat": None, "lon": None}, ensure_ascii=False)


def go_next_page(sub_link):
    try:
        next_btn = driver.find_element(By.XPATH, '//li/a[contains(text(), "بعد")]')
        driver.execute_script("arguments[0].click();", next_btn)
        elements = driver.find_elements(By.XPATH, "//div[contains(@class, 'attention')]")
        if len(elements) > 1:
            # logging.info("ℹ️ Account limitation.")
            driver.get(sub_link)
            return False
        else:
            # logging.info("➡ Moved to next page.")
            return True
    except NoSuchElementException:
        # logging.info("ℹ️ No next page button.")
        return False
    except Exception as e:
        # logging.warning(f"⚠️ Cannot go to next page: {e}")
        return False


# ----------------- Extract Data -----------------
def extract_data(category_name, subcat_name, sub_name, sub_link):
    try:
        for i in range(31):
            dropdown = wait.until(
                EC.presence_of_element_located((By.XPATH, "//div[contains(@class,'selectize-input')]")))
            dropdown.click()
            time.sleep(1)

            all_opts = driver.find_elements(By.XPATH, '//div[@class="selectize-dropdown-content"]/div')
            province = all_opts[i]
            province_name = province.text.strip()
            logging.info(f"➡ Selecting province: {province_name}")

            scroll_click(province)
            time.sleep(0.5)

            try:
                filter_btn = driver.find_element(By.XPATH, '//button[contains(@class,"filter-submit")]')
                filter_btn.click()
                time.sleep(2)
            except:
                pass
                # logging.warning("⚠ Filter button not found!")

            try:
                no_result = driver.find_element(By.XPATH,
                                                '//p[contains(@class,"search-count") and contains(text(),"نتیجه‌ای یافت نشد")]')
                if no_result:
                    # logging.info(f"ℹ️ No results for province: {province_name}, skipping...")
                    driver.get(sub_link)
                    time.sleep(2)
                    continue
            except NoSuchElementException:
                pass

            duplicate_count = 0
            while True:
                cards = driver.find_elements(By.XPATH, '//div[@class="content"]')
                # logging.info(f"📦 Cards found: {len(cards)}")

                for card in cards:
                    try:
                        phones_raw = [x.text.strip() for x in
                                      card.find_elements(By.XPATH, './/div[@data-print-adv="phone"]/span')]
                        phones = []
                        for p in phones_raw:
                            for expanded in expand_phone_range(p):
                                phones.append(expanded)
                        phone_number = "|".join(phones) if phones else "NoPhoneFoundInExpanded"
                    except:
                        phone_number = "NoPhoneFoundInXpath"

                    gis = extract_gis_from_card(card)

                    if phone_number in existing_phones and phone_number != 'NoPhoneFound':
                        duplicate_count += 1
                        # logging.info(f"⚠️ Duplicate phone found ({duplicate_count}/5): {phone_number}")
                        if duplicate_count >= 5:
                            # logging.warning("🚫 More than 5 duplicates on this page, skipping category...")
                            # return
                            break
                        continue
                    else:
                        duplicate_count = 0

                    address = get_element_text_safe(card, './/p[@data-print-adv="address"]')

                    try:
                        emails = [x.text.strip() for x in
                                  card.find_elements(By.XPATH, './/div[@data-print-adv="email"]/span')]
                        email = "|".join(emails)
                    except:
                        email = "NoEmailFound"

                    name = get_element_text_safe(card, './/h2/a')
                    specialty = get_element_text_safe(card, './/div[contains(@class,"keywords")]')
                    specialty += ' | ' + get_element_text_safe(card, './/p[contains(@class,"print-postal-hidden")]')

                    row = [name, specialty, phone_number, address, email, category_name, subcat_name, sub_name, gis]
                    save_to_database(row)

                if not (duplicate_count < 5 and go_next_page(sub_link)):
                    break

    except Exception as e:
        # driver.quit()
        # conn.close()
        logging.error(f"❌ Province loop error: {e}")


existing_phones = load_existing_phones(cursor)

# ----------------- Main Loop -----------------
try:
    categories = wait.until(EC.presence_of_all_elements_located((By.XPATH, '//*[@id="directory"]/div[1]/ul/li')))
except:
    logging.error("❌ Cannot load categories.")
    driver.quit()
    exit()

# logging.info(f"📂 Category count: {len(categories)}")
skipped_categories = int(input('how many categories skipped? '))

for main_cat_index, cat in enumerate(categories):
    if skipped_categories > main_cat_index:
        continue

    cat_name = get_text_safe(cat)
    logging.info(f"======== CATEGORY: {cat_name} ({main_cat_index+1}) ========")
    scroll_click(cat)
    time.sleep(1)

    subs_info_list = []
    subcats = driver.find_elements(By.XPATH, '//*[@id="tab-wrapper"]/div[' + str(
        main_cat_index + 1) + ']//ul[@class="topic"]/li/button')
    for sub_cat_index, subcat in enumerate(subcats):
        subcat_name = get_text_safe(subcat)
        # logging.info(f"   ➜ SubCategory: {subcat_name}")
        if subcat_name == '' or subcat_name == 'NoTextFound':
            continue

        scroll_click(subcat)
        time.sleep(0.1)

        subs = driver.find_elements(By.XPATH,
                                    '//*[@id="tab-wrapper"]/div[' + str(
                                        main_cat_index + 1) + ']/div[2]/div[not(@hidden)]//li/a')

        for sub in subs:
            link = sub.get_attribute("href")
            name = sub.text
            subs_info_list.append((subcat_name, sub_cat_index, link, name))

    skipped_link = int(input('how many link skipped? '))
    i = 0

    for subcat_name, sub_cat_index, link, name in subs_info_list:
        i += 1
        if skipped_link >= i:
            continue
        driver.get(link)

        logging.info(f"      ➜ Subsidiary: {name} ({i}) of {subcat_name} ({sub_cat_index})")
        extract_data(cat_name, subcat_name, name, link)

    driver.get(start_url)
    # exit()

logging.info("✅ Scraping finished successfully!")
driver.quit()
conn.close()
