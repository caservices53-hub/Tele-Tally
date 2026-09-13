from __future__ import annotations

import json
import os

from .job_engine import JobEngine

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:  # pragma: no cover
    raise SystemExit("MCP dependency missing. Install with: pip install -e '.[mcp]'") from e

mcp=FastMCP("gpt-tally-connect-pro-v2")
engine=JobEngine()

@mcp.tool()
def tally_status() -> str:
    """Check Tally connectivity and report the currently open/configured company."""
    try: return json.dumps({"ok":True,"company":engine.gateway.ping(),"url":engine.settings.tally_url})
    except Exception as e: return json.dumps({"ok":False,"error":str(e)})

@mcp.tool()
def study_company(from_date: str, to_date: str) -> str:
    """Read Tally history and learn recurring company-specific voucher/ledger patterns."""
    try: return json.dumps(engine.study_company(from_date,to_date),ensure_ascii=False)
    except Exception as e: return f"ERROR: {e}"

@mcp.tool()
def create_import_job(file_path: str, sheet: str = "", company: str = "") -> str:
    """Create a staged bulk import job from CSV/XLSX/JSON. Does not post to Tally."""
    try:
        jid=engine.create_job_from_file(file_path,sheet,company)
        return json.dumps(engine.summary(jid),ensure_ascii=False)
    except Exception as e: return f"ERROR: {e}"

@mcp.tool()
def create_import_job_from_json(rows_json: str, source_name: str = "chat-bulk-json", company: str = "") -> str:
    """Create a staged job from a JSON list of transactions."""
    try:
        rows=json.loads(rows_json)
        if not isinstance(rows,list): raise ValueError("rows_json must be a list")
        jid=engine.create_job_from_rows(rows,source_name,company)
        return json.dumps(engine.summary(jid),ensure_ascii=False)
    except Exception as e: return f"ERROR: {e}"

@mcp.tool()
def get_job_summary(job_id: str) -> str:
    try: return json.dumps(engine.summary(job_id),ensure_ascii=False)
    except Exception as e: return f"ERROR: {e}"

@mcp.tool()
def get_job_exceptions(job_id: str) -> str:
    """Return only unresolved/failed rows so the user can teach new patterns once."""
    try: return json.dumps(engine.exceptions(job_id),ensure_ascii=False)
    except Exception as e: return f"ERROR: {e}"

@mcp.tool()
def get_job_preview(job_id: str, limit: int = 500) -> str:
    """Preview resolved and unresolved rows before approval/posting."""
    try: return json.dumps(engine.preview(job_id,limit),ensure_ascii=False)
    except Exception as e: return f"ERROR: {e}"

@mcp.tool()
def teach_mapping(job_id: str, row_id: int, entries_json: str, party_ledger: str = "", bank_ledger: str = "", apply_to_similar: bool = True) -> str:
    """Save a verified accounting pattern and reclassify similar unresolved rows in the job."""
    try:
        entries=json.loads(entries_json)
        return json.dumps(engine.teach_row(job_id,row_id,entries,party_ledger,bank_ledger,apply_to_similar),ensure_ascii=False)
    except Exception as e: return f"ERROR: {e}"

@mcp.tool()
def approve_job(job_id: str) -> str:
    """Approve only after all exceptions are resolved. This still does not post."""
    try: return json.dumps(engine.approve(job_id),ensure_ascii=False)
    except Exception as e: return f"ERROR: {e}"

@mcp.tool()
def post_job(job_id: str, confirm_company: str) -> str:
    """Post an approved job to Tally in batches with failure isolation and company guard."""
    try: return json.dumps(engine.post(job_id,confirm_company),ensure_ascii=False)
    except Exception as e: return f"ERROR: {e}"

@mcp.tool()
def list_learned_rules(company: str, limit: int = 100) -> str:
    try: return json.dumps(engine.learning.list_rules(company,limit),ensure_ascii=False)
    except Exception as e: return f"ERROR: {e}"


def _run_http():
    token=os.getenv("TALLY_MCP_TOKEN","").strip()
    if not token:
        raise SystemExit("Set TALLY_MCP_TOKEN before HTTP mode.")
    import uvicorn
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse
    app=mcp.streamable_http_app()
    class Bearer(BaseHTTPMiddleware):
        async def dispatch(self,request,call_next):
            if request.headers.get("authorization","") != f"Bearer {token}":
                return JSONResponse({"error":"unauthorized"},status_code=401)
            return await call_next(request)
    app.add_middleware(Bearer)
    uvicorn.run(app,host=os.getenv("TALLY_MCP_HOST","127.0.0.1"),port=int(os.getenv("TALLY_MCP_PORT","8000")),log_level="info")


def main():
    if os.getenv("TALLY_MCP_TRANSPORT","stdio").lower()=="http": _run_http()
    else: mcp.run()

if __name__=="__main__": main()
