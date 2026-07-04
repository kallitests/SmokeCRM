from __future__ import annotations
import logging
import os
import time
import uuid
from datetime import datetime, timezone

from analyser import analyse_failures
from alerts import send_email_alert, send_slack_alert
from catalogue import SMOKE_TESTS
from models import AlertPayload, RunReport
from runner import run_smoke_suite
from storage import save_run

logger = logging.getLogger(__name__)
ENVIRONMENT = os.getenv("APP_ENV", "staging")
HAIKU_INPUT_COST = 0.00000025
HAIKU_OUTPUT_COST = 0.00000125


async def execute_pipeline() -> RunReport:
    """
    Pipeline complet :
    1. Exécute tous les smoke tests en parallèle (Playwright)
    2. Filtre les échecs → appel Claude unique (batch optimisé)
    3. Alerte Slack + email si échec critique
    4. Sauvegarde en base SQLite
    5. Retourne le rapport complet
    """
    run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    logger.info("▶ Démarrage run %s sur %s", run_id, ENVIRONMENT)
    start = time.monotonic()

    results = await run_smoke_suite(SMOKE_TESTS)
    failures = [r for r in results if r.status in ("failed", "error")]

    logger.info(
        "Run %s : %d/%d passés, %d échecs",
        run_id,
        len(results) - len(failures),
        len(results),
        len(failures),
    )

    diagnoses, tokens_used = [], 0
    if failures:
        logger.info("Analyse Claude de %d échec(s) en batch...", len(failures))
        diagnoses, tokens_used = await analyse_failures(failures)

    cost_eur = round(
        tokens_used * (HAIKU_INPUT_COST + HAIKU_OUTPUT_COST) / 2, 6
    )

    report = RunReport(
        run_id=run_id,
        environment=ENVIRONMENT,
        timestamp=datetime.now(timezone.utc),
        total=len(results),
        passed=len(results) - len(failures),
        failed=len(failures),
        duration_seconds=round(time.monotonic() - start, 2),
        results=results,
        diagnoses=diagnoses,
        tokens_used=tokens_used,
        cost_eur=cost_eur,
    )

    if failures:
        alert = AlertPayload(
            run_id=run_id,
            environment=ENVIRONMENT,
            failed_tests=failures,
            diagnoses=diagnoses,
            timestamp=report.timestamp,
        )
        await send_slack_alert(alert)
        send_email_alert(alert)

    await save_run(report)
    logger.info(
        "✓ Run %s terminé — %d tokens, %.4f € — durée %.1fs",
        run_id,
        tokens_used,
        cost_eur,
        report.duration_seconds,
    )
    return report
