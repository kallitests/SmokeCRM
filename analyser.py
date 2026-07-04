from __future__ import annotations
import json
import logging
import os

import anthropic
from models import FailureDiagnosis, RunResult

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """Tu es un analyste QA senior expert en APIs REST.
Analyse les échecs de smoke tests Playwright fournis.
Réponds UNIQUEMENT avec un tableau JSON valide, sans texte avant ni après.
Format strict pour chaque élément :
{"test_id":"","root_cause":"","category":"selector|timing|data|environment|bug","confidence":0.0,"suggested_fix":"","is_real_bug":true,"jira_priority":"Critical|High|Medium|Low"}"""

HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-6"
HAIKU_INPUT_COST = 0.00000025
HAIKU_OUTPUT_COST = 0.00000125


def _compress_failure(result: RunResult) -> str:
    """Compresse un échec en contexte minimal — max 150 tokens."""
    return (
        f"id={result.test_id} "
        f"endpoint={result.endpoint} "
        f"method={result.method} "
        f"code={result.status_code or 'timeout'} "
        f"err={result.error_message or 'unknown'} "
        f"ms={result.duration_ms}"
    )


async def analyse_failures(
    failures: list[RunResult],
) -> tuple[list[FailureDiagnosis], int]:
    """
    UN SEUL appel Claude pour tous les échecs groupés.
    Retourne (diagnostics, tokens_used).
    Utilise Haiku pour minimiser les coûts.
    """
    if not failures:
        return [], 0

    compressed = "\n".join(_compress_failure(f) for f in failures)
    user_message = f"Analyse ces {len(failures)} échecs :\n{compressed}"

    logger.debug("Appel Claude Haiku — %d échecs batchés", len(failures))

    response = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    tokens_used = response.usage.input_tokens + response.usage.output_tokens
    cost = (
        response.usage.input_tokens * HAIKU_INPUT_COST
        + response.usage.output_tokens * HAIKU_OUTPUT_COST
    )
    logger.info(
        "Tokens utilisés : %d (%.4f €) — réduction vs brut : -%.0f%%",
        tokens_used,
        cost,
        (1 - tokens_used / max(len(failures) * 2000, 1)) * 100,
    )

    raw = response.content[0].text.strip()

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            parsed = [parsed]
    except json.JSONDecodeError:
        logger.error("JSON invalide retourné par Claude : %s", raw[:200])
        return [], tokens_used

    diagnoses: list[FailureDiagnosis] = []
    for item in parsed:
        try:
            diagnoses.append(
                FailureDiagnosis(
                    test_id=item["test_id"],
                    root_cause=item["root_cause"],
                    category=item["category"],
                    confidence=float(item["confidence"]),
                    suggested_fix=item["suggested_fix"],
                    is_real_bug=bool(item["is_real_bug"]),
                    jira_priority=item["jira_priority"],
                    tokens_used=tokens_used // len(parsed),
                )
            )
        except (KeyError, ValueError) as exc:
            logger.warning("Erreur parsing diagnostic : %s — %s", exc, item)

    return diagnoses, tokens_used
