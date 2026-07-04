from __future__ import annotations
import json
import logging
import os
import smtplib
from email.mime.text import MIMEText

import httpx
from models import AlertPayload

logger = logging.getLogger(__name__)
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL", "")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")


def _emoji(priority: str) -> str:
    return {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢"}.get(priority, "⚪")


async def send_slack_alert(payload: AlertPayload) -> bool:
    """Envoie une alerte Slack avec diagnostic Claude intégré."""
    if not SLACK_WEBHOOK:
        logger.warning("SLACK_WEBHOOK_URL non configuré — alerte ignorée")
        return False

    diag_map = {d.test_id: d for d in payload.diagnoses}
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🚨 SmokeCRM — {len(payload.failed_tests)} échec(s) sur {payload.environment}",
            },
        },
        {"type": "divider"},
    ]

    for result in payload.failed_tests:
        diag = diag_map.get(result.test_id)
        prio = diag.jira_priority if diag else "Medium"
        fix = diag.suggested_fix if diag else "Analyse manuelle requise"
        cause = diag.root_cause if diag else result.error_message

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{_emoji(prio)} *{result.method} {result.endpoint}*\n"
                        f"Code : `{result.status_code or 'timeout'}` · {result.duration_ms} ms\n"
                        f"*Cause* : {cause}\n"
                        f"*Fix* : {fix}"
                    ),
                },
            }
        )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Run ID : `{payload.run_id}` · {payload.timestamp.strftime('%Y-%m-%d %H:%M UTC')}",
                }
            ],
        }
    )

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            SLACK_WEBHOOK,
            content=json.dumps({"blocks": blocks}),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
    success = resp.status_code == 200
    if success:
        logger.info("Alerte Slack envoyée — %d échecs", len(payload.failed_tests))
    else:
        logger.error("Slack erreur %s : %s", resp.status_code, resp.text[:200])
    return success


def send_email_alert(payload: AlertPayload) -> bool:
    """Envoie un email récapitulatif des échecs avec diagnostic."""
    if not all([ALERT_EMAIL, SMTP_USER, SMTP_PASS]):
        logger.warning("Config email incomplète — alerte email ignorée")
        return False

    diag_map = {d.test_id: d for d in payload.diagnoses}
    lines = [
        f"SmokeCRM — {len(payload.failed_tests)} smoke test(s) en échec",
        f"Environnement : {payload.environment}",
        f"Horodatage : {payload.timestamp.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]

    for result in payload.failed_tests:
        diag = diag_map.get(result.test_id)
        lines += [
            f"{'─'*50}",
            f"❌ {result.method} {result.endpoint}",
            f"   Code : {result.status_code or 'timeout'} | Durée : {result.duration_ms} ms",
        ]
        if diag:
            lines += [
                f"   Cause : {diag.root_cause}",
                f"   Fix   : {diag.suggested_fix}",
                f"   Prio  : {diag.jira_priority}",
            ]
        lines.append("")

    body = "\n".join(lines)
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"[SmokeCRM] 🚨 {len(payload.failed_tests)} échec(s) — {payload.environment}"
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_EMAIL

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, ALERT_EMAIL, msg.as_string())
        logger.info("Email d'alerte envoyé à %s", ALERT_EMAIL)
        return True
    except Exception as exc:
        logger.error("Erreur envoi email : %s", exc)
        return False
