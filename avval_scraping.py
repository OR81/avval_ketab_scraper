from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import ElementClickInterceptedException, NoSuchElementException
from selenium.webdriver.common.keys import Keys
import time
import logging
import json
import re
import mysql.connector

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ----------------- Database setup -----------------
conn = mysql.connector.connect(
    host='localhost',
    user='phpmyadmin',
    password='phpmy@dmin',
    port=3306,
    database='iranian_users'
)
cursor = conn.cursor()

def save_to_database(data):
    try:
        sql = """
            INSERT INTO avval_data
            (name, specialty, phone_number, address, email, category, subcategory, subsidiary, gis)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """
        
        cursor.execute(sql, data)
        conn.commit()
        logging.info(f"💾 Saved: {data[0]}")
        # TODO existing_phones.append(phone) also split |
    except Exception as e:
        logging.error(f"❌ DB error: {e}")
        conn.rollback()

# ----------------- Browser setup -----------------
chrome_options = Options()
chrome_options.add_argument("--headless=new")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
# chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--window-size=1280,1024")

service = Service("bin/chromedriver")
driver = webdriver.Chrome(service=service, options=chrome_options)
wait = WebDriverWait(driver, 10)

start_url = "https://avval.ir/"
driver.get(start_url)
time.sleep(2)

# ----------------- Helper Functions -----------------
def scroll_click(element):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        time.sleep(0.4)
        element.click()
        # time.sleep(0.7)
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", element)
        # time.sleep(0.7)

def get_text_safe(el):
    try:
        return el.text.strip()
    except:
        return "NoTextFound."

def load_existing_phones(cursor):
    """Load all existing phone numbers from database into a set"""
    existing = set()
    cursor.execute("SELECT phone_number FROM avval_data WHERE phone_number IS NOT NULL AND phone_number != ''")
    for (phone,) in cursor.fetchall():
        existing.add(phone.strip()) # split |
    logging.info(f"📱 Loaded {len(existing)} existing phone numbers from database.")
    return existing

def clean_sub_name(full_text):
    text = full_text.strip()
    text = text.replace("بهترین", "").strip()
    if "در" in text:
        text = text.split("در")[0].strip()
    return text



def wait_for_dropdown(driver, timeout=10):
    try:
        return WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[contains(@class,'selectize-input')]")
            )
        )
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

def go_next_page():
    try:
        next_btn = driver.find_element(By.XPATH, '//ul[@class="pagination"]/li/a[contains(text(),"»")]')
        #if has inactive , logging.info("ℹ️ No other card exist.")
        #return False
        
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

# ----------------- Extract Data -----------------
def extract_data(category_name, subcat_name, sub_name, sub_link):
    try:
        
        # location_box =wait.until(EC.presence_of_element_located((By.XPATH, "//input[contains(@class, 'input-style') and contains(@class, 'where')]")))
        # location_box.click()
        # time.sleep(0.1)
        # location_box.clear()
        # time.sleep(0.1)
        # location_box.send_keys(Keys.ENTER)
        
       
        dropdown = wait.until(
            EC.presence_of_element_located((By.XPATH, "//div[contains(@class,'selectize-input')]"))
        )
        dropdown.click()
        time.sleep(1)

        options = driver.find_elements(By.XPATH, '//div[@class="selectize-dropdown-content"]/div')
        logging.info(f"📍 Provinces found: {len(options)}")

        for i in range(len(options)):
            driver.get(sub_link)
            time.sleep(2)

            dropdown = wait.until(EC.presence_of_element_located((By.XPATH, "//div[contains(@class,'selectize-input')]")))
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
                time.sleep(2) # TODO not needed
            except:
                logging.warning("⚠ Filter button not found!")

            try:
                no_result = driver.find_element(
                    By.XPATH,
                    '//p[contains(@class,"search-count") and contains(text(),"نتیجه‌ای یافت نشد")]'
                )
                if no_result:
                    logging.info(f"ℹ️ No results for province: {province_name} , skipping...")
                    continue
            except NoSuchElementException:
                pass
                
            duplicate_count = 0
            while True:
                # time.sleep(2)

                cards = driver.find_elements(By.XPATH, '//div[@class="content"]')
                logging.info(f"📦 Cards found: {len(cards)}")

                for card in cards:
                    name = get_text_safe(card.find_element(By.XPATH, './/h2/a'))
                    specialty = get_text_safe(card.find_element(By.XPATH, './/div[contains(@class,"keywords")]'))

                    try:
                        phones = [x.text.strip() for x in card.find_elements(By.XPATH, './/div[@data-print-adv="phone"]/span')]
                        phone_number = "|".join(phones)
                    except:
                        phone_number= 'NoPhoneFound'
                    
                    address = get_text_safe(card.find_element(By.XPATH, './/p[@data-print-adv="address"]'))

                    try:
                        emails = [x.text.strip() for x in card.find_elements(By.XPATH, './/div[@data-print-adv="email"]/span')]
                        email = "|".join(emails)
                    except:
                        email = "NoEmailFound"

                    gis = extract_gis_from_card(card)

                    if phone_number in existing_phones and phone_number != 'NoPhoneFound':
                        duplicate_count += 1
                        logging.info(f"⚠️ Duplicate phone found ({duplicate_count}/5): {phone_number}")
                        if duplicate_count > 5:
                            logging.warning("🚫 More than 5 duplicates on this page, skipping category...")
                            break
                        continue
                    else:
                        duplicate_count = 0

                    row = [
                        name, specialty, phone_number, address, email,
                        category_name, subcat_name, sub_name, gis
                    ]

                    save_to_database(row)

                if not go_next_page():
                    break

    except Exception as e:
        driver.quit()
        conn.close()
        logging.error(f"❌ Province loop error: {e}")


existing_phones = load_existing_phones(cursor)

# ----------------- Main Loop -----------------
try:
    categories = wait.until(
        EC.presence_of_all_elements_located((By.XPATH, '//*[@id="directory"]/div[1]/ul/li'))
    )
except:
    logging.error("❌ Cannot load categories.")
    driver.quit()
    exit()

logging.info(f"📂 Category count: {len(categories)}")

for c_idx in range(len(categories)):
    categories = driver.find_elements(By.XPATH, '//*[@id="directory"]/div[1]/ul/li')
    cat = categories[c_idx]
    cat_name = get_text_safe(cat)

    logging.info(f"======== CATEGORY: {cat_name} ========")
    scroll_click(cat)
    time.sleep(1)

    subcats = driver.find_elements(By.XPATH, "//ul[@class='topic']/li/button")
    for s_idx in range(len(subcats)):
        subcats = driver.find_elements(By.XPATH, "//ul[@class='topic']/li/button")
        subcat = subcats[s_idx]
        subcat_name = get_text_safe(subcat)

        logging.info(f"   ➜ SubCategory: {subcat_name}")
        scroll_click(subcat)
        time.sleep(1)

        subs = driver.find_elements(By.XPATH, "//*[@id='directory']/div[1]//a")
        subs_info_list = []

        for sub in subs:
            sub_link = sub.get_attribute("href")
            subs_info_list.append((sub_link))

        for sub_link in subs_info_list:
            driver.get(sub_link)
            time.sleep(2)

            try:
                h1 = driver.find_element(By.TAG_NAME, "h1")
                full_text = h1.text
                sub_name = clean_sub_name(full_text)
            except NoSuchElementException:
                sub_name = ""

            logging.info(f"      ➜ Subsidiary: {sub_name}")

            extract_data(cat_name, subcat_name, sub_name, sub_link)

    driver.get(start_url)
    time.sleep(2)

logging.info("✅ Scraping finished successfully!")
driver.quit()
conn.close()
