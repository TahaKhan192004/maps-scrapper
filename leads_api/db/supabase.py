import logging
from functools import lru_cache
from typing import Dict, List, Optional
from supabase import create_client, Client
from config import get_settings
from schemas import LeadUpdate

TABLE = "google map leads"
TABLE1="leads"
logger = logging.getLogger(__name__)


@lru_cache
def _client() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_service_key)


def upsert_lead(lead: Dict) -> Optional[Dict]:
    """Insert lead into TABLE1, map to LeadUpdate and insert into leads table."""
    try:
        # 1. Upsert original lead into TABLE1
        resp1 = _client().table(TABLE).upsert(lead, on_conflict="business_name,keyword").execute()

        # 2. Map to LeadUpdate and upsert into `leads` table
        emails = lead.get("emails") or []
        primary_email = emails[0] if emails else None
        lead_update_data = {
            "first_name":       "there",
            "last_name":        None,
            "email":            primary_email,
            "business_name":    lead.get("business_name"),
            "industry":         lead.get("keyword"), 
            "location":         lead.get("address"),
            "phone":            lead.get("phone"),
            "website":          lead.get("website",None),
            "source_platform":  "google map",
            "specifications":   lead.get("business_summary"),
            "bundle_id":        f"{lead.get('keyword')}bundle" if lead.get("keyword") else None,
            "status":           "new",
        }

        resp2 = _client().table("leads").upsert(lead_update_data, on_conflict="email").execute()

        return {
            "lead_record":        resp1.data[0] if resp1.data else None,
            "lead_update_record": resp2.data[0] if resp2.data else None,
        }

    except Exception as e:
        logger.error("Upsert failed for %s: %s", lead.get("business_name"), e)
        return None


def bulk_upsert(leads: List[Dict]) -> int:
    return sum(1 for lead in leads if upsert_lead(lead))


def fetch_leads(keyword: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict]:
    try:
        q = _client().table(TABLE).select("*").order("created_at", desc=True)
        if keyword:
            q = q.ilike("keyword", f"%{keyword}%")
        return q.range(offset, offset + limit - 1).execute().data or []
    except Exception as e:
        logger.error("Fetch failed: %s", e)
        return []
