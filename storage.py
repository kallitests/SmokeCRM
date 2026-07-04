from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
from models import RunReport, RunResult, FailureDiagnosis

logger = logging.getLogger(__name__)
DB_PATH = Path("smokecrm.db")


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                environment TEXT,
                timestamp TEXT,
                total INTEGER,
                passed INTEGER,
                failed INTEGER,
                duration_seconds REAL,
                tokens_used INTEGER,
                cost_eur REAL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                test_id TEXT,
                test_name TEXT,
                endpoint TEXT,
                method TEXT,
                status TEXT,
                status_code INTEGER,
                duration_ms INTEGER,
                error_message TEXT,
                environment TEXT,
                timestamp TEXT,
                root_cause TEXT,
                category TEXT,
                suggested_fix TEXT,
                jira_priority TEXT,
                is_real_bug INTEGER,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            )
        """)
        await db.commit()
    logger.info("Base de données initialisée : %s", DB_PATH)


async def save_run(report: RunReport) -> None:
    diag_map = {d.test_id: d for d in report.diagnoses}
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO runs
               (run_id, environment, timestamp, total, passed, failed,
                duration_seconds, tokens_used, cost_eur)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                report.run_id,
                report.environment,
                report.timestamp.isoformat(),
                report.total,
                report.passed,
                report.failed,
                report.duration_seconds,
                report.tokens_used,
                report.cost_eur,
            ),
        )
        for result in report.results:
            diag = diag_map.get(result.test_id)
            await db.execute(
                """INSERT INTO results
                   (run_id, test_id, test_name, endpoint, method, status,
                    status_code, duration_ms, error_message, environment,
                    timestamp, root_cause, category, suggested_fix,
                    jira_priority, is_real_bug)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    report.run_id,
                    result.test_id,
                    result.test_name,
                    result.endpoint,
                    result.method,
                    result.status,
                    result.status_code,
                    result.duration_ms,
                    result.error_message,
                    result.environment,
                    result.timestamp.isoformat(),
                    diag.root_cause if diag else None,
                    diag.category if diag else None,
                    diag.suggested_fix if diag else None,
                    diag.jira_priority if diag else None,
                    int(diag.is_real_bug) if diag else None,
                ),
            )
        await db.commit()
    logger.info("Run %s sauvegardé (%d résultats)", report.run_id, len(report.results))


async def get_recent_runs(limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM runs ORDER BY timestamp DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def get_recent_results(limit: int = 50) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM results ORDER BY timestamp DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def get_token_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT SUM(tokens_used), SUM(cost_eur), COUNT(*) FROM runs"
        ) as cur:
            row = await cur.fetchone()
            return {
                "total_tokens": row[0] or 0,
                "total_cost_eur": round(row[1] or 0, 4),
                "total_runs": row[2] or 0,
            }
