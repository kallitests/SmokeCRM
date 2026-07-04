from __future__ import annotations
import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from playwright.async_api import async_playwright
from models import RunResult, SmokeTest

logger = logging.getLogger(__name__)
BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:3000")
ENVIRONMENT = os.getenv("APP_ENV", "staging")
TIMEOUT_MS = 30_000


async def run_single_test(
    test: SmokeTest,
    request_context,
) -> RunResult:
    """Exécute un smoke test API via Playwright request context."""
    start = time.monotonic()
    try:
        method = test.method.lower()
        url = f"{BASE_URL}{test.endpoint}"
        kwargs: dict = {"timeout": TIMEOUT_MS}
        if test.headers:
            kwargs["headers"] = test.headers
        if test.payload and method in ("post", "put", "patch"):
            kwargs["data"] = test.payload

        response = await getattr(request_context, method)(url, **kwargs)
        duration_ms = int((time.monotonic() - start) * 1000)
        passed = response.status == test.expected_status

        return RunResult(
            test_id=test.id,
            test_name=test.name,
            endpoint=test.endpoint,
            method=test.method,
            status="passed" if passed else "failed",
            status_code=response.status,
            duration_ms=duration_ms,
            error_message=None if passed else f"Expected {test.expected_status}, got {response.status}",
            environment=ENVIRONMENT,
            timestamp=datetime.now(timezone.utc),
        )

    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning("Test %s erreur : %s", test.id, exc)
        return RunResult(
            test_id=test.id,
            test_name=test.name,
            endpoint=test.endpoint,
            method=test.method,
            status="error",
            status_code=None,
            duration_ms=duration_ms,
            error_message=str(exc),
            environment=ENVIRONMENT,
            timestamp=datetime.now(timezone.utc),
        )


async def run_smoke_suite(tests: list[SmokeTest]) -> list[RunResult]:
    """Lance toute la suite en parallèle via un seul browser context."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        request_ctx = context.request

        tasks = [run_single_test(t, request_ctx) for t in tests]
        results = await asyncio.gather(*tasks)

        await context.close()
        await browser.close()

    logger.info(
        "Suite terminée : %d/%d passés",
        sum(1 for r in results if r.status == "passed"),
        len(results),
    )
    return list(results)
