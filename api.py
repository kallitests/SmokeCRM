from __future__ import annotations
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from catalogue import SMOKE_TESTS
from orchestrator import execute_pipeline
from storage import get_recent_results, get_recent_runs, get_token_stats, init_db

logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"), format="%(asctime)s %(levelname)-8s %(name)s — %(message)s")
logger = logging.getLogger(__name__)
INTERVAL = int(os.getenv("RUN_INTERVAL_MINUTES","15"))
ENVIRONMENT = os.getenv("APP_ENV","staging")

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    scheduler.add_job(execute_pipeline, "interval", minutes=INTERVAL, id="smoke_suite")
    scheduler.start()
    logger.info("Scheduler démarré — run toutes les %d min", INTERVAL)
    yield
    scheduler.shutdown()

app = FastAPI(title="SmokeCRM", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def _build_trend_data(runs):
    today = datetime.now(timezone.utc).date()
    labels, pass_data, fail_data = [], [], []
    run_map = {}
    for r in runs:
        try:
            d = datetime.fromisoformat(r["timestamp"]).date().isoformat()
            p, f = run_map.get(d,(0,0))
            run_map[d] = (p+r["passed"], f+r["failed"])
        except Exception:
            pass
    for i in range(13,-1,-1):
        d = (today - timedelta(days=i)).isoformat()
        labels.append(d[5:])
        p, f = run_map.get(d,(0,0))
        pass_data.append(p); fail_data.append(f)
    return {"labels":labels,"pass":pass_data,"fail":fail_data}

def _build_kpis(runs, results):
    total_tests = len(SMOKE_TESTS)
    total_runs = len(runs)
    if not runs:
        return {"total_tests":total_tests,"pass_rate":0,"passed":0,"failed":0,"not_run":total_tests,"total_runs":0}
    last = runs[0]
    passed = last.get("passed",0); failed = last.get("failed",0); total = last.get("total",1)
    pass_rate = round(passed/max(total,1)*100)
    return {"total_tests":total_tests,"pass_rate":pass_rate,"passed":passed,"failed":failed,"not_run":max(0,total_tests-total),"total_runs":total_runs}

def _build_failures(results):
    if not results: return []
    last_ts = results[0].get("timestamp","")[:13]
    return [r for r in results if r.get("status")!="passed" and r.get("timestamp","")[:13]==last_ts]

def _token_stats_with_last(stats, runs):
    last_tokens = runs[0].get("tokens_used",0) if runs else 0
    last_cost = runs[0].get("cost_eur",0.0) if runs else 0.0
    return {**stats,"last_run_tokens":last_tokens,"last_run_cost":last_cost}

@app.get("/")
async def dashboard(request: Request):
    runs = await get_recent_runs(limit=50)
    results = await get_recent_results(limit=30)
    stats = await get_token_stats()
    return templates.TemplateResponse("dashboard.html",{
        "request":request,"active":"dashboard","environment":ENVIRONMENT,
        "kpis":_build_kpis(runs,results),"recent_results":results[:15],
        "failures":_build_failures(results),"trend_data":_build_trend_data(runs),
        "token_stats":_token_stats_with_last(stats,runs),"flash":None,
    })

@app.post("/run")
async def trigger_run_ui(request: Request):
    try:
        await execute_pipeline()
        return RedirectResponse("/?flash=success", status_code=303)
    except Exception as exc:
        logger.error("Erreur run UI : %s", exc)
        return RedirectResponse("/?flash=error", status_code=303)

@app.get("/tests")
async def tests_view(request: Request):
    return templates.TemplateResponse("tests.html",{
        "request":request,"active":"tests",
        "tests":[t.model_dump() for t in SMOKE_TESTS],"total":len(SMOKE_TESTS),
    })

@app.get("/runs")
async def runs_view(request: Request):
    runs = await get_recent_runs(limit=50)
    return templates.TemplateResponse("runs.html",{"request":request,"active":"runs","runs":runs})

@app.post("/api/run")
async def api_run():
    report = await execute_pipeline()
    return {"run_id":report.run_id,"passed":report.passed,"failed":report.failed,"tokens_used":report.tokens_used}

@app.get("/api/runs")
async def api_runs(limit: int=20):
    return await get_recent_runs(limit=limit)

@app.get("/api/results")
async def api_results(limit: int=50):
    return await get_recent_results(limit=limit)

@app.get("/api/health")
async def health():
    return {"status":"ok","scheduler":scheduler.running,"environment":ENVIRONMENT}
