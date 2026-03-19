import logging
import uuid
from typing import Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from db.supabase import fetch_leads
from pipeline import run_pipeline
from scrapers.summary import summarize_website
from schemas import JobResponse, JobStatusResponse, Lead, ScrapeRequest, ScrapeResponse

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
for lib in ("selenium", "urllib3", "httpx"):
    logging.getLogger(lib).setLevel(logging.WARNING)

# ── In-memory job store (simple; no Redis needed) ─────────────────────────────
# Structure: { job_id: { "status": str, "result": dict|None, "error": str|None } }
_jobs: Dict[str, Dict] = {}

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Google Maps Lead Scraper",
    description="Scrapes Maps → Website → Firecrawl and stores leads in Supabase.",
    version="1.0.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── Background worker ─────────────────────────────────────────────────────────
def _run_in_background(job_id: str, body: ScrapeRequest):
    _jobs[job_id]["status"] = "running"
    try:
        leads = run_pipeline(
            search_query=body.search_query,
            max_leads=body.max_leads,
            run_website_scraper=body.run_website_scraper,
            run_summary=body.run_summary,
        )
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["result"] = {
            "keyword": body.search_query,
            "total_leads": len(leads),
            "leads": leads,
        }
    except Exception as e:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(e)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/debug/summary", summary="Debug Gemini summary for a single URL")
def debug_summary(url: str):
    settings = get_settings()
    summary = summarize_website(url, api_key=settings.gemini_api_key)
    if not summary:
        raise HTTPException(status_code=502, detail="No summary returned; check logs for details.")
    return {"url": url, "summary": summary}


@app.post("/scrape/sync", response_model=ScrapeResponse, summary="Scrape synchronously (blocks)")
def scrape_sync(body: ScrapeRequest):
    """Runs the full pipeline and returns when done. Good for small queries (≤5 leads)."""
    try:
        leads = run_pipeline(
            search_query=body.search_query,
            max_leads=body.max_leads,
            run_website_scraper=body.run_website_scraper,
            run_summary=body.run_summary,
        )
        return ScrapeResponse(keyword=body.search_query, total_leads=len(leads), leads=leads)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/scrape/async", response_model=JobResponse, status_code=202, summary="Scrape in background")
def scrape_async(body: ScrapeRequest, background_tasks: BackgroundTasks):
    """Queues the pipeline as a background task. Poll /jobs/{job_id} for status."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "pending", "result": None, "error": None}
    background_tasks.add_task(_run_in_background, job_id, body)
    return JobResponse(
        job_id=job_id,
        status="pending",
        message=f"Job started. Poll GET /jobs/{job_id}",
    )


@app.get("/jobs/{job_id}", response_model=JobStatusResponse, summary="Check job status")
def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = None
    if job["result"]:
        result = ScrapeResponse(**job["result"])

    return JobStatusResponse(
        job_id=job_id,
        status=job["status"],
        result=result,
        error=job.get("error"),
    )


@app.get("/leads", response_model=List[Lead], summary="List stored leads from Supabase")
def list_leads(
    keyword: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    rows = fetch_leads(keyword=keyword, limit=limit, offset=offset)
    return [Lead(**r) for r in rows]
