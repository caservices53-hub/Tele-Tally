from __future__ import annotations

import os

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .job_engine import JobEngine

VERSION = "0.3.0"
engine = JobEngine()


def _token() -> str:
    return os.getenv("GPT_TALLY_BRIDGE_TOKEN", "").strip()


def _json_error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "GPT-Tally Local Bridge", "version": VERSION})


async def status(_: Request) -> JSONResponse:
    try:
        company = engine.gateway.ping()
        return JSONResponse({
            "ok": True,
            "bridge_version": VERSION,
            "tally_url": engine.settings.tally_url,
            "company": company,
            "configured_company": engine.settings.tally_company,
        })
    except Exception as exc:
        return _json_error(str(exc), 503)


async def study(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        result = engine.study_company(str(body.get("from_date", "")), str(body.get("to_date", "")), str(body.get("company", "")))
        return JSONResponse({"ok": True, "result": result})
    except Exception as exc:
        return _json_error(str(exc))


async def create_job(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        rows = body.get("rows")
        if not isinstance(rows, list) or not rows:
            return _json_error("rows must be a non-empty JSON list")
        if len(rows) > 50000:
            return _json_error("A single browser job is limited to 50,000 rows. Split larger imports into multiple files.")
        jid = engine.create_job_from_rows(rows, str(body.get("source_name", "browser-import")), str(body.get("company", "")))
        return JSONResponse({"ok": True, "job_id": jid, "summary": engine.summary(jid)})
    except Exception as exc:
        return _json_error(str(exc))


async def job_summary(request: Request) -> JSONResponse:
    try:
        return JSONResponse({"ok": True, "summary": engine.summary(request.path_params["job_id"])})
    except Exception as exc:
        return _json_error(str(exc), 404)


async def job_preview(request: Request) -> JSONResponse:
    try:
        limit = int(request.query_params.get("limit", "500"))
        return JSONResponse({"ok": True, "rows": engine.preview(request.path_params["job_id"], limit)})
    except Exception as exc:
        return _json_error(str(exc), 404)


async def job_exceptions(request: Request) -> JSONResponse:
    try:
        return JSONResponse({"ok": True, "rows": engine.exceptions(request.path_params["job_id"])})
    except Exception as exc:
        return _json_error(str(exc), 404)


async def teach(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        entries = body.get("entries")
        if not isinstance(entries, list) or len(entries) < 2:
            return _json_error("entries must contain at least two ledger legs")
        result = engine.teach_row(
            request.path_params["job_id"],
            int(body["row_id"]),
            entries,
            str(body.get("party_ledger", "")),
            str(body.get("bank_ledger", "")),
            bool(body.get("apply_to_similar", True)),
        )
        return JSONResponse({"ok": True, "result": result})
    except Exception as exc:
        return _json_error(str(exc))


async def approve(request: Request) -> JSONResponse:
    try:
        return JSONResponse({"ok": True, "result": engine.approve(request.path_params["job_id"])})
    except Exception as exc:
        return _json_error(str(exc))


async def post(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        confirm_company = str(body.get("confirm_company", "")).strip()
        if not confirm_company:
            return _json_error("confirm_company is required")
        return JSONResponse({"ok": True, "result": engine.post(request.path_params["job_id"], confirm_company)})
    except Exception as exc:
        return _json_error(str(exc))


async def rules(request: Request) -> JSONResponse:
    try:
        company = request.query_params.get("company", "") or engine.settings.tally_company or engine.gateway.current_company()
        limit = int(request.query_params.get("limit", "100"))
        return JSONResponse({"ok": True, "company": company, "rules": engine.learning.list_rules(company, limit)})
    except Exception as exc:
        return _json_error(str(exc))


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path == "/api/health":
            return await call_next(request)
        expected = _token()
        if not expected:
            return _json_error("GPT_TALLY_BRIDGE_TOKEN is not configured on this PC", 503)
        if request.headers.get("authorization", "") != f"Bearer {expected}":
            return _json_error("Unauthorized local bridge request", 401)
        return await call_next(request)


class PrivateNetworkMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        if request.headers.get("access-control-request-private-network", "").lower() == "true":
            response.headers["Access-Control-Allow-Private-Network"] = "true"
        response.headers["X-GPT-Tally-Bridge"] = VERSION
        response.headers["Cache-Control"] = "no-store"
        return response


routes = [
    Route("/api/health", health, methods=["GET", "OPTIONS"]),
    Route("/api/status", status, methods=["GET", "OPTIONS"]),
    Route("/api/study", study, methods=["POST", "OPTIONS"]),
    Route("/api/jobs", create_job, methods=["POST", "OPTIONS"]),
    Route("/api/jobs/{job_id}/summary", job_summary, methods=["GET", "OPTIONS"]),
    Route("/api/jobs/{job_id}/preview", job_preview, methods=["GET", "OPTIONS"]),
    Route("/api/jobs/{job_id}/exceptions", job_exceptions, methods=["GET", "OPTIONS"]),
    Route("/api/jobs/{job_id}/teach", teach, methods=["POST", "OPTIONS"]),
    Route("/api/jobs/{job_id}/approve", approve, methods=["POST", "OPTIONS"]),
    Route("/api/jobs/{job_id}/post", post, methods=["POST", "OPTIONS"]),
    Route("/api/rules", rules, methods=["GET", "OPTIONS"]),
]

allowed = [x.strip() for x in os.getenv("GPT_TALLY_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if x.strip()]
middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=allowed,
        allow_origin_regex=r"https://([a-z0-9-]+\.)*vercel\.app$",
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Access-Control-Request-Private-Network"],
        expose_headers=["X-GPT-Tally-Bridge"],
        max_age=600,
    ),
    Middleware(PrivateNetworkMiddleware),
    Middleware(AuthMiddleware),
]

app = Starlette(debug=False, routes=routes, middleware=middleware)


def main() -> None:
    host = os.getenv("GPT_TALLY_BRIDGE_HOST", "127.0.0.1")
    port = int(os.getenv("GPT_TALLY_BRIDGE_PORT", "8788"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
