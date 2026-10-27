"""
FastAPI application for url-shortener service.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from url_shortener.database import Database
from url_shortener.models import AnalyticsResponse, ShortenRequest, ShortenResponse
from url_shortener.shortener import generate_short_code
from url_shortener.snowflake import default_snowflake


def create_app(db: Optional[Database] = None) -> FastAPI:
    """Factory function to build and configure the FastAPI application."""
    app = FastAPI(
        title="URL Shortener API",
        description="Production-grade URL shortening, redirection, and telemetry engine built with FastAPI and SQLite.",
        version="1.0.0"
    )

    # Use provided database instance (e.g. for testing) or default to local SQLite file
    app.state.db = db if db is not None else Database("urls.db")

    @app.get("/health", tags=["System"])
    def health_check():
        """Health check endpoint for container probes."""
        return {"status": "ok", "service": "url-shortener"}

    @app.post(
        "/api/shorten",
        response_model=ShortenResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["Shortener"]
    )
    def shorten_url(payload: ShortenRequest, request: Request):
        """
        Creates a shortened URL for the requested destination.
        Optionally accepts a custom alias and a TTL in seconds.
        """
        db_instance: Database = app.state.db
        now_utc = datetime.now(timezone.utc)
        created_at_str = now_utc.isoformat()

        # Compute expiration time if TTL is provided
        expires_at_str: Optional[str] = None
        if payload.ttl_seconds is not None:
            expires_dt = now_utc + timedelta(seconds=payload.ttl_seconds)
            expires_at_str = expires_dt.isoformat()

        short_code: str
        if payload.custom_code:
            short_code = payload.custom_code
            inserted = db_instance.insert_url(
                short_code=short_code,
                target_url=payload.url,
                created_at=created_at_str,
                expires_at=expires_at_str
            )
            if not inserted:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Custom short code '{short_code}' is already in use. Please select a different code."
                )
        else:
            # Auto-generate with collision retry loop
            inserted = False
            for _ in range(5):
                candidate = default_snowflake.generate_code() if payload.use_snowflake else generate_short_code()
                if db_instance.insert_url(
                    short_code=candidate,
                    target_url=payload.url,
                    created_at=created_at_str,
                    expires_at=expires_at_str
                ):
                    short_code = candidate
                    inserted = True
                    break
            if not inserted:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to generate a unique short code after multiple attempts."
                )

        # Build full short URL based on the incoming request Host header
        base_url = str(request.base_url).rstrip("/")
        short_url = f"{base_url}/{short_code}"

        return ShortenResponse(
            short_code=short_code,
            short_url=short_url,
            target_url=payload.url,
            created_at=created_at_str,
            expires_at=expires_at_str
        )

    @app.get(
        "/api/analytics/{short_code}",
        response_model=AnalyticsResponse,
        tags=["Analytics"]
    )
    def get_analytics(short_code: str):
        """Retrieves click statistics, creation/expiry timestamps, and recent click events."""
        db_instance: Database = app.state.db
        stats = db_instance.get_analytics(short_code)
        if stats is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Short code '{short_code}' not found."
            )
        return AnalyticsResponse(**stats)

    @app.get("/{short_code}", tags=["Redirection"])
    def redirect_url(short_code: str, request: Request):
        """
        Redirects users to the original destination URL via HTTP 307.
        Validates expiration and records click telemetry.
        """
        db_instance: Database = app.state.db
        url_record = db_instance.get_url(short_code)

        if url_record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Short URL '{short_code}' not found."
            )

        # Check if URL has expired
        if url_record.get("expires_at"):
            try:
                exp_dt = datetime.fromisoformat(url_record["expires_at"])
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) >= exp_dt:
                    raise HTTPException(
                        status_code=status.HTTP_410_GONE,
                        detail="Short URL has expired."
                    )
            except ValueError:
                pass

        # Record telemetry asynchronously or synchronously
        user_agent = request.headers.get("user-agent")
        referer = request.headers.get("referer")
        client_ip = request.client.host if request.client else None
        now_str = datetime.now(timezone.utc).isoformat()

        db_instance.record_click(
            url_id=url_record["id"],
            clicked_at=now_str,
            user_agent=user_agent,
            referer=referer,
            ip_address=client_ip
        )

        # HTTP 307 preserves the HTTP method and indicates a temporary redirect
        return RedirectResponse(
            url=url_record["target_url"],
            status_code=status.HTTP_307_TEMPORARY_REDIRECT
        )

    return app


# Default module-level instance for ASGI servers (uvicorn url_shortener.app:app)
app = create_app()
