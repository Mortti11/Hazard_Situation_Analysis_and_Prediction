from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .llm import generate_ai_summary
from .pipeline import assess_journey, fetch_route_options
from .schemas import JourneyAnalysisResponse, JourneyRequest, RouteOptionsResponse, RoutePreview

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
SITE_DIR = APP_DIR.parent.parent / "website_without_EDA"

app = FastAPI(title="Route Risk Backend")
# /static = the maintained journey-UI assets that the dashboard links to.
# Mounted before /, so a stale copy under website_without_EDA/static/ is shadowed.
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def home():
    return FileResponse(SITE_DIR / "hsap-dashboard.html")


@app.get("/api/v1/route-options", response_model=RouteOptionsResponse)
def route_options(departure: str, destination: str):
    try:
        previews = fetch_route_options(departure, destination)
    except EnvironmentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return RouteOptionsResponse(
        departure=departure,
        destination=destination,
        routes=[RoutePreview(**preview) for preview in previews])


@app.post("/api/v1/route-analysis", response_model=JourneyAnalysisResponse)
def route_analysis(request: JourneyRequest, include_ai: bool = Query(False)):
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


# Catch-all for the rest of the website (dashboard, EDA, hsap-style.css,
# all_hazard_final_map_v10.html, dummyfile.csv). API routes and /static/* are
# already registered above and win first.
app.mount("/", StaticFiles(directory=str(SITE_DIR), html=True), name="site")
