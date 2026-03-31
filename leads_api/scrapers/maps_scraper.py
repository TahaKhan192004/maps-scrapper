import logging
import os
import time
from typing import Dict, List

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)


def _build_driver(headless: bool) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--log-level=3")                    # suppress Chrome INFO/WARNING logs
    opts.add_argument("--silent")
    # ── Memory caps (critical on low-RAM VMs) ────────────────────────────────
    opts.add_argument("--js-flags=--max-old-space-size=256")  # cap JS heap to 256 MB
    opts.add_argument("--renderer-process-limit=1")            # only one renderer process
    opts.add_argument("--memory-pressure-off")
    # ─────────────────────────────────────────────────────────────────────────
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    opts.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    # Disable GCM / push notifications that cause PHONE_REGISTRATION_ERROR spam
    opts.add_experimental_option("prefs", {
        "profile.managed_default_content_settings.notifications": 2,
        "gcm_channel_status": 0,
    })

    # FIX: open devnull first, then close it after the driver starts to avoid file handle leak
    _devnull = open(os.devnull, "w")
    service = ChromeService(log_output=_devnull)
    driver = webdriver.Chrome(service=service, options=opts)
    _devnull.close()  # safe to close — ChromeDriver has already started

    return driver


def _extract_details(driver: webdriver.Chrome, name_fallback: str = "") -> Dict:
    def get_text(xpath):
        try:
            return driver.find_element(By.XPATH, xpath).text
        except Exception:
            return ""

    data = {}
    data['business_name'] = get_text('/html/body/div[1]/div[2]/div[9]/div[8]/div/div/div[1]/div[2]/div/div[1]/div/div/div[2]/div/div[1]/div[1]/h1')
    data['rating'] = get_text('//div[@role="img"] | //span[@aria-hidden="true" and contains(text(), ".")]')
    if data['rating'] and len(data['rating']) > 4:
        data['rating'] = data['rating'][:3]

    data['phone'] = get_text('//button[contains(@data-item-id, "phone")]')
    data['address'] = get_text('//button[contains(@data-item-id, "address")]')
    data['website'] = get_text('//a[contains(@data-item-id, "authority") or @aria-label="Website"]')

    if data['phone']:   data['phone']   = data['phone'].split("\n")[-1]
    if data['address']: data['address'] = data['address'].split("\n")[-1]
    if data['website']: data['website'] = data['website'].replace('\ue80b', '').strip()

    if not data['business_name']:
        data['business_name'] = name_fallback

    return data


def scrape_google_maps(search_query: str, max_leads: int = 10, headless: bool = True) -> List[Dict]:
    logger.info("Maps scrape | query=%s max=%d", search_query, max_leads)

    # FIX: initialise to None so the finally block is always safe
    driver = None
    try:
        driver = _build_driver(headless)
    except Exception as e:
        logger.error("Failed to build Chrome driver: %s", e)
        return []

    wait = WebDriverWait(driver, 20)
    captured: List[Dict] = []

    try:
        driver.get("https://www.google.com/maps")
        box = wait.until(EC.presence_of_element_located((By.NAME, "q")))
        driver.execute_script("arguments[0].click();", box)
        time.sleep(0.8)
        box.clear()
        box.send_keys(search_query)
        box.send_keys(Keys.ENTER)
        time.sleep(5)

        try:
            feed = driver.find_element(By.XPATH, '//div[@role="feed"]')
        except Exception:
            feed = driver.find_element(By.TAG_NAME, "body")

        processed: set = set()
        scroll_count = 0
        consecutive_failures = 0

        while len(captured) < max_leads and scroll_count < 25:
            try:
                links = driver.find_elements(By.XPATH, '//a[contains(@href, "/maps/place")]')
            except Exception:
                links = []

            candidate = None
            candidate_url = ""

            for link in links:
                try:
                    url = link.get_attribute("href") or ""
                    if "/maps/place" in url and url not in processed:
                        candidate = link
                        candidate_url = url
                        break
                except Exception:
                    continue

            if candidate:
                try:
                    processed.add(candidate_url)
                    name_fallback = candidate.get_attribute("aria-label") or ""

                    driver.execute_script("arguments[0].scrollIntoView(true);", candidate)
                    time.sleep(0.8)
                    driver.execute_script("arguments[0].click();", candidate)
                    time.sleep(3)

                    data = _extract_details(driver, name_fallback)
                    data["maps_url"] = candidate_url

                    if data.get("business_name"):
                        logger.info("Captured: %s", data["business_name"])
                        captured.append(data)
                        consecutive_failures = 0
                    else:
                        consecutive_failures += 1

                except Exception as e:
                    logger.warning("Click failed: %s", e)
                    consecutive_failures += 1
            else:
                try:
                    driver.execute_script("arguments[0].scrollBy(0, 600);", feed)
                    time.sleep(3)
                    scroll_count += 1
                except Exception:
                    break

            if consecutive_failures > 5:
                break

    except Exception as e:
        logger.error("Maps error: %s", e)
    finally:
        # FIX: guard against driver being None if _build_driver raised
        if driver is not None:
            driver.quit()

    logger.info("Maps done | captured=%d", len(captured))
    return captured