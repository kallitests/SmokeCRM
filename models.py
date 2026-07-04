from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, HttpUrl


class SmokeTest(BaseModel):
    id: str
    name: str
    endpoint: str
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"]
    expected_status: int = 200
    criticality: Literal["critical", "high", "medium", "low"]
    tags: list[str] = []
    payload: dict | None = None
    headers: dict | None = None


class RunResult(BaseModel):
    test_id: str
    test_name: str
    endpoint: str
    method: str
    status: Literal["passed", "failed", "error"]
    status_code: int | None
    duration_ms: int
    error_message: str | None = None
    environment: str
    timestamp: datetime


class FailureDiagnosis(BaseModel):
    test_id: str
    root_cause: str
    category: Literal["selector", "timing", "data", "environment", "bug"]
    confidence: float
    suggested_fix: str
    is_real_bug: bool
    jira_priority: Literal["Critical", "High", "Medium", "Low"]
    tokens_used: int


class RunReport(BaseModel):
    run_id: str
    environment: str
    timestamp: datetime
    total: int
    passed: int
    failed: int
    duration_seconds: float
    results: list[RunResult]
    diagnoses: list[FailureDiagnosis] = []
    tokens_used: int = 0
    cost_eur: float = 0.0


class AlertPayload(BaseModel):
    run_id: str
    environment: str
    failed_tests: list[RunResult]
    diagnoses: list[FailureDiagnosis]
    timestamp: datetime
