import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .llm import generate_ai_summary
from .pipeline import assess_journey, fetch_route_options
from .schemas import JourneyAnalysisResponse, JourneyRequest, RouteOptionsResponse, RoutePreview

_HERE = Path(__file__).resolve().parent
_STATIC_DIR = _HERE / "static"

_env_file = _HERE.parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file)
    for old, new in {"Open_ai_key": "OPENAI_API_KEY", "openrouteservice": "ORS_API_KEY"}.items():
        if os.environ.get(old) and not os.environ.get(new):
            os.environ[new] = os.environ[old]

app = FastAPI(title="Route Risk Backend", version="0.1.0")

if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def serve_ui():
    index = _STATIC_DIR / "index.html"
    if not index.exists():
        raise HTTPException(
            status_code=500,
            detail="UI page not found: static/index.html is missing.")
    return HTMLResponse(content=index.read_text(encoding="utf-8"))


@app.get("/api/v1/route-options", response_model=RouteOptionsResponse)
def route_options(departure: str, destination: str):
    try:
        previews = fetch_route_options(departure, destination)
    except EnvironmentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return RouteOptionsResponse(
        departure=departure,
        destination=destination,
        routes=[RoutePreview(**preview) for preview in previews],
    )


@app.post("/api/v1/route-analysis", response_model=JourneyAnalysisResponse)
def route_analysis(
    request: JourneyRequest,
    include_ai: bool = Query(False, description="Include AI summary")):
    try:
        result = assess_journey(request)
    except EnvironmentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if include_ai:
        try:
            result.ai_summary = generate_ai_summary(
                result.route_summary,
                result.journey_risk_summary,
                result.evidence_for_llm)
        except Exception as exc:
            result.ai_summary_error = f"AI summary unavailable: {exc}"

    return result
