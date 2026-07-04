from __future__ import annotations
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from models import RunResult


def make_failure(test_id: str = "SMK-001") -> RunResult:
    return RunResult(
        test_id=test_id,
        test_name="Test login",
        endpoint="/api/auth/login",
        method="POST",
        status="failed",
        status_code=500,
        duration_ms=2535,
        error_message="500 Internal Server Error",
        environment="staging",
        timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_analyse_failures_empty():
    from analyser import analyse_failures
    diagnoses, tokens = await analyse_failures([])
    assert diagnoses == []
    assert tokens == 0


@pytest.mark.asyncio
async def test_analyse_failures_single(monkeypatch):
    """Vérifie que le diagnostic est correctement parsé depuis la réponse Claude."""
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text=json.dumps([{
                "test_id": "SMK-001",
                "root_cause": "Connexion PostgreSQL expirée",
                "category": "environment",
                "confidence": 0.92,
                "suggested_fix": "Redémarrer le pool de connexions",
                "is_real_bug": True,
                "jira_priority": "Critical",
            }])
        )
    ]
    mock_response.usage = MagicMock(input_tokens=150, output_tokens=80)

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    import analyser
    monkeypatch.setattr(analyser, "client", mock_client)

    failures = [make_failure("SMK-001")]
    diagnoses, tokens = await analyser.analyse_failures(failures)

    assert len(diagnoses) == 1
    assert diagnoses[0].test_id == "SMK-001"
    assert diagnoses[0].category == "environment"
    assert diagnoses[0].jira_priority == "Critical"
    assert diagnoses[0].is_real_bug is True
    assert tokens == 230
    mock_client.messages.create.assert_called_once()


@pytest.mark.asyncio
async def test_analyse_failures_batch(monkeypatch):
    """Vérifie qu'un seul appel Claude est fait pour plusieurs échecs."""
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text=json.dumps([
                {"test_id": "SMK-001", "root_cause": "DB timeout", "category": "environment",
                 "confidence": 0.9, "suggested_fix": "Redémarrer DB", "is_real_bug": True,
                 "jira_priority": "Critical"},
                {"test_id": "SMK-004", "root_cause": "Index manquant", "category": "data",
                 "confidence": 0.8, "suggested_fix": "Ajouter index", "is_real_bug": True,
                 "jira_priority": "High"},
            ])
        )
    ]
    mock_response.usage = MagicMock(input_tokens=200, output_tokens=120)

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    import analyser
    monkeypatch.setattr(analyser, "client", mock_client)

    failures = [make_failure("SMK-001"), make_failure("SMK-004")]
    diagnoses, tokens = await analyser.analyse_failures(failures)

    assert len(diagnoses) == 2
    assert tokens == 320
    # UN SEUL appel pour 2 échecs — c'est le point clé de l'optimisation
    assert mock_client.messages.create.call_count == 1


@pytest.mark.asyncio
async def test_analyse_failures_invalid_json(monkeypatch):
    """L'agent ne doit pas crasher si Claude retourne du JSON invalide."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Désolé, je ne peux pas analyser cela.")]
    mock_response.usage = MagicMock(input_tokens=100, output_tokens=20)

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    import analyser
    monkeypatch.setattr(analyser, "client", mock_client)

    diagnoses, tokens = await analyser.analyse_failures([make_failure()])
    assert diagnoses == []
    assert tokens == 120
