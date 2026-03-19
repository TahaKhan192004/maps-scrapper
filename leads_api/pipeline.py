"""
Runs Maps → Website Scraper → Summary (Gemini), merges results, saves to Supabase.
"""
import logging
from typing import List, Dict

from config import get_settings
from scrapers.maps_scraper import scrape_google_maps
from scrapers.website_scraper import scrape_website
from scrapers.summary import summarize_website
from db.supabase import bulk_upsert,upsert_lead

logger = logging.getLogger(__name__)


def run_pipeline(
    search_query: str,
    max_leads: int = 10,
    run_website_scraper: bool = True,
    run_summary: bool = True,
) -> List[Dict]:
    settings = get_settings()
    logger.info("Pipeline start | query=%s", search_query)

    raw_leads = scrape_google_maps(search_query, max_leads=max_leads)
    enriched: List[Dict] = []

    for raw in raw_leads:
        website = raw.get("website", "")
        emails, summary = [], None
        socials = {"linkedin": [], "facebook": [], "instagram": []}

        if run_website_scraper and website:
            try:
                ws = scrape_website(website)
                emails = ws.get("emails", [])
                socials = ws.get("socials", socials)
            except Exception as e:
                logger.warning("Website scraper failed %s: %s", website, e)

        if run_summary and website:
            try:
                summary = summarize_website(website, api_key=settings.gemini_api_key)
            except Exception as e:
                logger.warning("Summary failed %s: %s", website, e)

        lead = {
            "business_name":    raw.get("business_name"),
            "phone":            raw.get("phone"),
            "address":          raw.get("address"),
            "rating":           raw.get("rating"),
            "website":          website or None,
            "maps_url":         raw.get("maps_url"),
            "keyword":          search_query,
            "emails":           sorted(set(emails)),
            "socials":          socials,
            "business_summary": summary,
        }
        enriched.append(lead)
        upsert_lead(lead)  # Save each lead immediately to ensure we don't lose data if pipeline fails midway

    logger.info("Pipeline done | leads=%d saved=%d", len(raw_leads), len(enriched))
    return enriched