"""
Fast website scraper.
Strategy:
  1. Try pure requests first (no browser overhead) — covers ~70% of sites
  2. Fall back to Selenium only if requests fails or finds nothing
  3. Scrape homepage + contact pages in parallel threads
  4. Replace all fixed sleeps with smart explicit waits
"""
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Set

import requests
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_SOCIAL_RE = {
    "linkedin":  re.compile(r"https?://(www\.)?linkedin\.com/[^\s\"'>]+", re.I),
    "facebook":  re.compile(r"https?://(www\.)?facebook\.com/[^\s\"'>]+", re.I),
    "instagram": re.compile(r"https?://(www\.)?instagram\.com/[^\s\"'>]+", re.I),
}
_CONTACT_KW = ["contact", "about", "support", "team", "staff"]
_BANNED_EXT = (".png", ".jpg", ".svg", ".css", ".js", ".ico", ".woff", ".pdf", ".zip")
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
_HEADERS = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}
_REQUEST_TIMEOUT = 8
_MAX_CONTACT_PAGES = 4
_MAX_THREADS = 5


def _normalize(url: str) -> str:
    url = url.replace("\ue80b", "").strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url.rstrip("/")


def _valid_email(e: str) -> bool:
    e = e.lower()
    return (
        len(e) <= 80
        and "example.com" not in e
        and "@2x" not in e
        and not any(e.endswith(x) for x in _BANNED_EXT)
    )


def _emails_from_html(html: str) -> Set[str]:
    emails = {e.lower() for e in _EMAIL_RE.findall(html) if _valid_email(e)}
    for match in re.findall(r'mailto:([^\'">\s?]+)', html, re.I):
        e = match.split("?")[0].lower()
        if _valid_email(e):
            emails.add(e)
    return emails


def _socials_from_html(html: str) -> Dict[str, Set[str]]:
    result = {k: set() for k in _SOCIAL_RE}
    for platform, pat in _SOCIAL_RE.items():
        for match in pat.findall(html):
            url = match.split("?")[0].rstrip("/")
            if not any(x in url for x in ["/share", "/intent", "/sharer"]):
                result[platform].add(url)
    return result


def _sitemap_contact_urls(base: str) -> List[str]:
    found: Set[str] = set()
    for path in ("/sitemap.xml", "/sitemap_index.xml"):
        try:
            r = requests.get(base + path, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
            if r.status_code == 200 and "<loc>" in r.text:
                found.update(re.findall(r"<loc>(.*?)</loc>", r.text))
        except Exception:
            pass
    return [
        u.rstrip("/") for u in found
        if any(k in u.lower() for k in _CONTACT_KW)
    ][:_MAX_CONTACT_PAGES]


def _fetch_html(url: str) -> str:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT, allow_redirects=True)
        if r.status_code == 200 and "text/html" in r.headers.get("Content-Type", ""):
            return r.text
    except Exception:
        pass
    return ""


def _homepage_contact_links(base: str, html: str) -> List[str]:
    links = set()
    for match in re.findall(r'href=["\']([^"\']+)["\']', html, re.I):
        if any(k in match.lower() for k in _CONTACT_KW):
            if match.startswith("http"):
                links.add(match.rstrip("/"))
            elif match.startswith("/"):
                links.add(base + match.rstrip("/"))
    return list(links)[:_MAX_CONTACT_PAGES]


def _scrape_url_fast(url: str) -> Dict:
    html = _fetch_html(url)
    if not html:
        return {"emails": set(), "socials": {k: set() for k in _SOCIAL_RE}}
    return {"emails": _emails_from_html(html), "socials": _socials_from_html(html)}


def _run_fast(base: str, contact_urls: List[str]) -> Dict:
    all_urls = list({base} | set(contact_urls))
    emails: Set[str] = set()
    socials: Dict[str, Set[str]] = {k: set() for k in _SOCIAL_RE}

    with ThreadPoolExecutor(max_workers=_MAX_THREADS) as ex:
        futures = {ex.submit(_scrape_url_fast, url): url for url in all_urls}
        for future in as_completed(futures):
            try:
                result = future.result()
                emails.update(result["emails"])
                for k, v in result["socials"].items():
                    socials[k].update(v)
            except Exception as e:
                logger.debug("Fast scrape failed %s: %s", futures[future], e)

    return {"emails": emails, "socials": socials}


def _make_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--log-level=3")
    opts.add_argument(f"user-agent={_UA}")
    opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    opts.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(15)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
    )
    return driver


def _scrape_url_selenium(driver: webdriver.Chrome, url: str) -> Dict:
    try:
        driver.get(url)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        WebDriverWait(driver, 3).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        html = driver.page_source
        return {"emails": _emails_from_html(html), "socials": _socials_from_html(html)}
    except (TimeoutException, WebDriverException) as e:
        logger.debug("Selenium failed %s: %s", url, e)
        return {"emails": set(), "socials": {k: set() for k in _SOCIAL_RE}}


def _run_selenium(base: str, contact_urls: List[str]) -> Dict:
    driver = _make_driver()
    emails: Set[str] = set()
    socials: Dict[str, Set[str]] = {k: set() for k in _SOCIAL_RE}
    try:
        for url in [base] + contact_urls[:_MAX_CONTACT_PAGES]:
            result = _scrape_url_selenium(driver, url)
            emails.update(result["emails"])
            for k, v in result["socials"].items():
                socials[k].update(v)
    finally:
        driver.quit()
    return {"emails": emails, "socials": socials}


def scrape_website(raw_url: str) -> Dict:
    """
    Scrape a website for emails and social links.

    Flow:
      1. Fetch homepage via requests (fast, no browser)
      2. Scrape all pages in parallel threads
      3. If requests blocked or empty → fall back to Selenium
    """
    base = _normalize(raw_url)
    logger.info("Website scrape | %s", base)
    start = time.time()

    contact_urls = _sitemap_contact_urls(base)
    homepage_html = _fetch_html(base)

    if homepage_html:
        if not contact_urls:
            contact_urls = _homepage_contact_links(base, homepage_html)

        result = _run_fast(base, contact_urls)

        if result["emails"] or any(result["socials"].values()):
            logger.info("Fast path done | %s | emails=%d | %.1fs",
                        base, len(result["emails"]), time.time() - start)
            return {
                "emails": sorted(result["emails"]),
                "socials": {k: sorted(v) for k, v in result["socials"].items()},
            }
        logger.info("Fast path empty, falling back to Selenium | %s", base)
    else:
        logger.info("Requests blocked, using Selenium | %s", base)

    result = _run_selenium(base, contact_urls)
    logger.info("Selenium done | %s | emails=%d | %.1fs",
                base, len(result["emails"]), time.time() - start)

    return {
        "emails": sorted(result["emails"]),
        "socials": {k: sorted(v) for k, v in result["socials"].items()},
    }