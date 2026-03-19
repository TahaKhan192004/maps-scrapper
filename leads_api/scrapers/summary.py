"""
Web Scraper + Business Analyzer
Scrapes a website, cleans text, then uses Gemini to:
  1. Summarize what the business does
  2. Identify how your AI-first software agency can help them

Usage:
    python scraper.py <url> --api-key <GEMINI_API_KEY>
    python scraper.py <url>                              # if GEMINI_API_KEY is set in env
"""

import sys
import os
import re
import argparse
import textwrap
import logging
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types


# ── CONFIG ────────────────────────────────────────────────────────────────────

SCRAPE_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "td", "title"]
NOISE_TAGS  = ["script", "style", "noscript", "nav", "footer", "header", "aside",
               "iframe", "svg", "form", "meta", "link"]
MAX_CHARS   = 12000   # max text fed to Gemini to stay within token budget
MODEL       = "gemini-2.5-flash"
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

SYSTEM_PROMPT = """\
You are a senior business analyst at an AI-first software agency.
Your agency offers:
  • Agentic AI systems   – autonomous agents, multi-agent pipelines, LLM workflows
  • Generative AI        – custom LLM integration, RAG, fine-tuning, AI content tools
  • Web development      – modern full-stack apps (Next.js, FastAPI, etc.)
  • AI Automation        – n8n, Make.com, Zapier, RPA, intelligent process automation
  • Data & Analytics     – dashboards, ETL pipelines, business intelligence
  • AI Consulting        – strategy, adoption roadmaps, AI audits

Given extracted text from a business website, produce a concise report in this exact structure:

## Business Summary
2–3 sentences describing what the business does, who they serve, and their value proposition.

## Industry & Scale
One line: industry vertical and estimated company size/stage.

## How We Can Help
List 3–5 specific, actionable opportunities where our agency's services can add real value.
For each opportunity:
  - Name the service category
  - Explain the specific problem or gap you spotted on their site
  - Describe the concrete solution we would deliver

## Priority Recommendation
One paragraph: the single highest-impact engagement to pitch first, and why.

Be specific and direct. No fluff. Base everything strictly on the scraped content.
"""


# ── SCRAPER ───────────────────────────────────────────────────────────────────

def fetch_html(url: str) -> str:
    """Fetch raw HTML from a URL with a browser-like user agent."""
    if not url.startswith("http"):
        url = "https://" + url
    resp = requests.get(url, headers=HEADERS, timeout=12)
    resp.raise_for_status()
    return resp.text, url


def extract_text(html: str) -> str:
    """Parse HTML, strip noise tags, extract visible text from content tags."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in NOISE_TAGS:
        for el in soup.find_all(tag):
            el.decompose()

    seen = set()
    lines = []
    for tag in SCRAPE_TAGS:
        for el in soup.find_all(tag):
            text = el.get_text(separator=" ", strip=True)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) < 5:
                continue
            if text in seen:
                continue
            seen.add(text)
            lines.append(f"[{tag.upper()}] {text}")

    return "\n".join(lines)


def clean_text(raw: str) -> str:
    """Trim to max chars and remove obvious cookie/legal boilerplate."""
    boilerplate = re.compile(
        r"(cookie|privacy policy|terms of service|all rights reserved"
        r"|copyright ©|\bGDPR\b|subscribe to our newsletter)",
        re.IGNORECASE
    )
    lines = [l for l in raw.splitlines() if not boilerplate.search(l)]
    text = "\n".join(lines)
    return text[:MAX_CHARS]


# ── GEMINI ────────────────────────────────────────────────────────────────────

def analyze_with_gemini(text: str, api_key: str, url: str) -> str:
    """Send cleaned text to Gemini and return the analysis report."""
    client = genai.Client(api_key=api_key)

    user_message = f"Website: {url}\n\nExtracted content:\n\n{text}"

    try:
        response = client.models.generate_content(
            model=MODEL,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=2000,
            ),
            contents=user_message,
        )
        if not getattr(response, "text", None):
            logger.warning("Gemini returned empty text for url=%s", url)
        return response.text
    except Exception as e:
        logger.exception("Gemini request failed for url=%s: %s", url, e)
        raise


def summarize_website(url: str, api_key: str) -> str | None:
    """Fetch, extract, and summarize a website with Gemini. Returns None on failure."""
    if not api_key:
        logger.warning("Gemini API key missing; skipping summary for url=%s", url)
        return None

    try:
        html, final_url = fetch_html(url)
        raw_text = extract_text(html)
        clean = clean_text(raw_text)
        if not clean:
            logger.warning("No usable text after cleaning for url=%s", final_url)
            return None
        logger.info("Gemini summary input chars=%d url=%s", len(clean), final_url)
        return analyze_with_gemini(clean, api_key, final_url)
    except Exception as e:
        logger.exception("Summarize failed for url=%s: %s", url, e)
        return None


# ── CLI ───────────────────────────────────────────────────────────────────────

def print_section(title: str, content: str):
    width = 72
    print(f"\n{'─' * width}")
    print(f"  {title}")
    print(f"{'─' * width}")
    print(content)


def main():
    parser = argparse.ArgumentParser(
        description="Scrape a business website and analyze it with Gemini."
    )
    parser.add_argument("url", help="The URL of the business website to analyze")
    parser.add_argument(
        "--api-key", default=os.getenv("GEMINI_API_KEY"),
        help="Gemini API key (or set GEMINI_API_KEY env var)"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable debug logging for summary execution"
    )
    args = parser.parse_args()

    if not args.api_key:
        print("ERROR: Gemini API key required. Pass --api-key or set GEMINI_API_KEY env var.")
        sys.exit(1)

    if args.debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )

    # Step 1 – Fetch
    print(f"\n→ Fetching {args.url} ...")
    try:
        html, final_url = fetch_html(args.url)
    except Exception as e:
        print(f"ERROR fetching page: {e}")
        sys.exit(1)
    print(f"  ✓ Got {len(html):,} bytes of HTML")

    # Step 2 – Extract & clean
    raw_text = extract_text(html)
    clean = clean_text(raw_text)
    print(f"  ✓ Extracted {len(clean):,} chars of clean text from {raw_text.count(chr(10))+1} elements")

    print_section("EXTRACTED TEXT (preview – first 800 chars)", clean[:800] + " ...")

    # Step 3 – Gemini analysis
    print(f"\n→ Sending to Gemini ({MODEL}) ...")
    try:
        report = analyze_with_gemini(clean, args.api_key, final_url)
    except Exception as e:
        print(f"ERROR from Gemini: {e}")
        sys.exit(1)

    print_section("BUSINESS ANALYSIS REPORT", report)
    print(f"\n{'─' * 72}\n")


if __name__ == "__main__":
    main()
