"""
Pydantic schemas and data validation models for url-shortener.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


SHORT_CODE_REGEX = re.compile(r"^[a-zA-Z0-9_-]{3,30}$")
ALLOWED_SCHEMES = ("http://", "https://")
BLOCKED_SCHEMES = ("javascript:", "data:", "file:", "vbscript:", "about:")


class ShortenRequest(BaseModel):
    """Request payload to shorten a destination URL."""
    url: str = Field(..., description="Target destination URL (must be HTTP or HTTPS)")
    custom_code: Optional[str] = Field(None, description="Optional custom alphanumeric alias (3-30 chars)")
    ttl_seconds: Optional[int] = Field(None, ge=1, le=31536000, description="Optional time-to-live in seconds (max 1 year)")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        lower = v.lower()
        for blocked in BLOCKED_SCHEMES:
            if lower.startswith(blocked):
                raise ValueError(f"URL scheme '{blocked}' is dangerous and not permitted.")
        if not lower.startswith(ALLOWED_SCHEMES):
            raise ValueError("Target URL must start with 'http://' or 'https://'.")
        if len(v) > 2048:
            raise ValueError("URL length exceeds maximum permitted 2048 characters.")
        return v

    @field_validator("custom_code")
    @classmethod
    def validate_custom_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not SHORT_CODE_REGEX.match(v):
            raise ValueError("Custom short code must be 3-30 characters long and contain only letters, digits, '_' or '-'.")
        return v


class ShortenResponse(BaseModel):
    """Response returned upon successfully registering a short URL."""
    short_code: str
    short_url: str
    target_url: str
    created_at: str
    expires_at: Optional[str] = None


class ClickEventItem(BaseModel):
    """Individual click event record for analytics."""
    clicked_at: str
    user_agent: Optional[str] = None
    referer: Optional[str] = None


class AnalyticsResponse(BaseModel):
    """Analytics summary for a specific short code."""
    short_code: str
    target_url: str
    total_clicks: int
    created_at: str
    expires_at: Optional[str] = None
    is_expired: bool
    recent_clicks: List[ClickEventItem] = Field(default_factory=list)
