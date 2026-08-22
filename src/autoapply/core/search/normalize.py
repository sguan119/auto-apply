"""Normalize JobSpy (and similar) rows into SearchJob. No pandas here."""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import ValidationError

from autoapply.core.contracts import SearchJob

log = logging.getLogger(__name__)

_TRACKING_QUERY_PREFIXES = ("utm_",)
_TRACKING_QUERY_KEYS = frozenset(
    {"fbclid", "gclid", "gclsrc", "li_fat_id", "mc_cid", "mc_eid"}
)


def canonicalize_url(url: str) -> str:
    """Lowercase scheme/host and drop common tracking query params (search-spec §5)."""
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_QUERY_KEYS
        and not k.lower().startswith(_TRACKING_QUERY_PREFIXES)
    ]
    host = parts.hostname.lower() if parts.hostname else parts.netloc
    if parts.port:
        host = f"{host}:{parts.port}"
    scheme = parts.scheme.lower() or "https"
    return urlunsplit((scheme, host, parts.path, urlencode(query), ""))


def job_id_for(platform_id: str | None, canonical_url: str) -> str:
    """Board id if present; otherwise a stable hash of the canonical URL."""
    if platform_id and str(platform_id).strip() and str(platform_id).lower() != "nan":
        return str(platform_id).strip()
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:16]


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = _as_str(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def choose_apply_url(job_url: str | None, job_url_direct: str | None) -> str | None:
    """Prefer the company/ATS link when JobSpy provides it (deliver-prd: company site first)."""
    direct = _as_str(job_url_direct)
    listing = _as_str(job_url)
    for candidate in (direct, listing):
        if candidate and candidate.lower().startswith(("http://", "https://")):
            return candidate
    return None


def normalize_jobspy_row(row: dict[str, Any], *, default_platform: str | None = None) -> SearchJob | None:
    """Turn one JobSpy-shaped dict into SearchJob. Returns None if required fields are missing."""
    url_raw = choose_apply_url(row.get("job_url"), row.get("job_url_direct"))
    if url_raw is None:
        log.debug("skip row with no http url: title=%r", row.get("title"))
        return None
    try:
        canonical = canonicalize_url(url_raw)
    except ValueError:
        return None

    platform = _as_str(row.get("site")) or default_platform
    title = _as_str(row.get("title"))
    company = _as_str(row.get("company")) or _as_str(row.get("company_name"))
    if not platform or not title or not company:
        log.debug("skip row missing platform/title/company: %r", row.get("title"))
        return None

    payload = {
        "platform": platform,
        "job_id": job_id_for(_as_str(row.get("id")), canonical),
        "url": canonical,
        "title": title,
        "company": company,
        "location": _as_str(row.get("location")),
        "description": _as_str(row.get("description")),
        "date_posted": _as_datetime(row.get("date_posted")),
        "extracted_yoe": None,
        "yoe_is_preferred": False,
    }
    try:
        return SearchJob.model_validate(payload)
    except ValidationError:
        log.debug("skip row that failed SearchJob validation: %s", payload.get("url"))
        return None
