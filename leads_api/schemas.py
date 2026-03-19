from typing import List, Optional
from pydantic import BaseModel, EmailStr
from uuid import UUID
from datetime import datetime

class SocialLinks(BaseModel):
    linkedin: List[str] = []
    facebook: List[str] = []
    instagram: List[str] = []


class Lead(BaseModel):
    business_name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    rating: Optional[str] = None
    website: Optional[str] = None
    maps_url: Optional[str] = None
    keyword: Optional[str] = None
    emails: List[str] = []
    socials: SocialLinks = SocialLinks()
    business_summary: Optional[str] = None

class LeadUpdate(BaseModel):
    id: Optional[UUID] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: EmailStr
    business_name: Optional[str] = None
    industry: Optional[str] = None
    location: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    source_platform: Optional[str] = None
    specifications: Optional[str] = None
    bundle_id: Optional[str] = None
    status: Optional[str] = "new"
    created_at: Optional[datetime] = None

class ScrapeRequest(BaseModel):
    search_query: str
    max_leads: int = 10
    run_website_scraper: bool = True
    run_summary: bool = True


class ScrapeResponse(BaseModel):
    keyword: str
    total_leads: int
    leads: List[Lead]


class JobResponse(BaseModel):
    job_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str   # pending | running | done | failed
    result: Optional[ScrapeResponse] = None
    error: Optional[str] = None
