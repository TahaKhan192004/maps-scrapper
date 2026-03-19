import logging
import re
from typing import Dict, List

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_BANNED_EXT = (".png", ".jpg", ".svg", ".css", ".js", ".ico", ".woff", ".pdf")
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def _valid_email(e: str) -> bool:
    e = e.lower()
    return (
        len(e) <= 80
        and "example.com" not in e
        and "@2x" not in e
        and not any(e.endswith(x) for x in _BANNED_EXT)
    )


def _extract_summary(html: str, max_chars: int = 500) -> str:
    """Strip HTML tags and return the first max_chars of visible text."""
    text = _TAG_RE.sub(" ", html)
    text = _SPACE_RE.sub(" ", text).strip()
    return text[:max_chars] if text else None


def firecrawl_extract(url: str, api_key: str) -> Dict:
    if not api_key:
        logger.warning("No FIRECRAWL_API_KEY, skipping %s", url)
        return {"emails": [], "summary": None}

    logger.info("Firecrawl | %s", url)

    try:
        from firecrawl import Firecrawl

        app = Firecrawl(api_key=api_key)
        data = app.scrape(url, formats=["html"])

        html = getattr(data, "html", "") or ""

        emails = sorted({
            e.lower() for e in _EMAIL_RE.findall(html)
            if _valid_email(e)
        })

        summary = _extract_summary(html)

        logger.info("Firecrawl done | %s emails=%d", url, len(emails))
        return {"emails": emails, "summary": summary}

    except ImportError:
        logger.error("firecrawl-py not installed. Run: pip install firecrawl-py")
    except Exception as e:
        logger.error("Firecrawl error %s: %s", url, e)

    return {"emails": [], "summary": None}