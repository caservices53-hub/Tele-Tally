"""Outbound-only relay between Telegram–Tally AI Cloud and GPT–Tally Connect Pro.

The relay accepts only canonical vouchers from the paired cloud tenant. It never
accepts arbitrary Tally XML and never exposes the local connector to the internet.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx

VERSION = "1.0.0"
STATE_FILE = Path(__file__).with_name("relay_state.json")
LOCAL_URL = os.getenv("TALLY_CONNECTOR_URL", "http://127.0.0.1:8788").rstrip("/")
CLOUD_URL = os.getenv("TELEGRAM_TALLY_CLOUD_URL", "").rstrip("/")


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Set {name} before starting the relay.")
    return value


def load_state() -> dict[str, str]:
    if not STATE_FILE.exists():
        raise RuntimeError("Relay is not paired. Run: python relay.py pair YOUR-CODE")
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(value: dict[str, str]) -> None:
    STATE_FILE.write_text(json.dumps(value, indent=2), encoding="utf-8")


async def pair(code: str) -> None:
    cloud = required("TELEGRAM_TALLY_CLOUD_URL").rstrip("/")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(f"{cloud}/api/bridge/pair", json={"code": code, "version": VERSION})
        response.raise_for_status()
        data = response.json()
    save_state({"cloud_url": cloud, "connector_id": data["connectorId"], "token": data["token"]})
    print("Paired successfully. The connector token is stored locally in relay_state.json.")


async def local_login(client: httpx.AsyncClient, role: str) -> str:
    prefix = f"TALLY_{role.upper()}"
    response = await client.post(f"{LOCAL_URL}/auth/login", json={
        "organisation_name": required("TALLY_ORGANISATION"),
        "email": required(f"{prefix}_EMAIL"),
        "password": required(f"{prefix}_PASSWORD"),
    })
    response.raise_for_status()
    return response.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def local_status(client: httpx.AsyncClient, maker_token: str) -> tuple[dict[str, Any], list[str]]:
    status = (await client.get(f"{LOCAL_URL}/status", headers=auth(maker_token))).json()
    companies_response = await client.get(f"{LOCAL_URL}/tally/companies", headers=auth(maker_token))
    companies_response.raise_for_status()
    return status, companies_response.json().get("companies", [])


async def execute_job(client: httpx.AsyncClient, job: dict[str, Any], maker_token: str, status: dict[str, Any], companies: list[str]) -> dict[str, Any]:
    company = job["companyName"]
    voucher = job["canonicalVoucher"]
    if company not in companies or voucher.get("company") != company:
        raise RuntimeError(f"Exact Tally company is not loaded: {company}")
    preview = await client.post(f"{LOCAL_URL}/vouchers/preview", params={"check_tally_ledgers": "true"}, json=voucher, headers=auth(maker_token))
    preview.raise_for_status()
    preview_data = preview.json()
    if not preview_data.get("valid"):
        messages = "; ".join(issue.get("message", "Validation issue") for issue in preview_data.get("issues", []))
        raise RuntimeError(f"Local Tally preview blocked the voucher: {messages}")
    submit = await client.post(f"{LOCAL_URL}/production/approvals", headers=auth(maker_token), json={
        "company_name": company, "action_type": "CORE_VOUCHER", "risk_level": "MEDIUM", "payload": voucher,
    })
    submit.raise_for_status()
    approval = submit.json()
    if not status.get("posting_enabled"):
        return {"state": "staged", "result": {"approval_id": approval["id"], "preview": preview_data, "reason": "Local live posting is disabled"}}
    if not os.getenv("TALLY_CHECKER_EMAIL") or not os.getenv("TALLY_EXECUTOR_EMAIL"):
        return {"state": "staged", "result": {"approval_id": approval["id"], "preview": preview_data, "reason": "Local maker-checker credentials are not configured"}}
    checker = await local_login(client, "checker")
    approved = await client.post(f"{LOCAL_URL}/production/approvals/{approval['id']}/approve", headers=auth(checker), json={"comment": "Approved from Telegram–Tally AI v1 after cloud owner review and local preview."})
    approved.raise_for_status()
    executor = await local_login(client, "executor")
    executed = await client.post(f"{LOCAL_URL}/production/approvals/{approval['id']}/execute", headers=auth(executor), json={})
    executed.raise_for_status()
    return {"success": True, "result": {"approval_id": approval["id"], "preview": preview_data, "execution": executed.json()}}


async def run_once(state: dict[str, str]) -> bool:
    cloud_headers = {"Authorization": f"Bearer {state['token']}"}
    async with httpx.AsyncClient(timeout=45) as client:
        maker = await local_login(client, "maker")
        status, companies = await local_status(client, maker)
        heartbeat = await client.post(f"{state['cloud_url']}/api/bridge/heartbeat", headers=cloud_headers, json={
            "version": VERSION, "companies": companies, "postingEnabled": bool(status.get("posting_enabled")),
        })
        heartbeat.raise_for_status()
        next_job = await client.post(f"{state['cloud_url']}/api/bridge/jobs/next", headers=cloud_headers)
        if next_job.status_code == 204:
            return False
        next_job.raise_for_status()
        job = next_job.json()
        try:
            completion = await execute_job(client, job, maker, status, companies)
        except Exception as exc:
            completion = {"success": False, "error": str(exc)}
        completion["leaseToken"] = job["leaseToken"]
        done = await client.post(f"{state['cloud_url']}/api/bridge/jobs/{job['id']}/complete", headers=cloud_headers, json=completion)
        done.raise_for_status()
        return True


async def serve() -> None:
    state = load_state()
    print(f"Telegram–Tally Relay {VERSION} is running. Local connector: {LOCAL_URL}")
    while True:
        try:
            worked = await run_once(state)
            await asyncio.sleep(1 if worked else 8)
        except (httpx.HTTPError, RuntimeError) as exc:
            print(f"Relay warning: {exc}")
            await asyncio.sleep(15)


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram–Tally AI secure outbound relay")
    sub = parser.add_subparsers(dest="command", required=True)
    pair_parser = sub.add_parser("pair", help="Pair this computer using a one-time dashboard code")
    pair_parser.add_argument("code")
    sub.add_parser("run", help="Run the relay continuously")
    args = parser.parse_args()
    asyncio.run(pair(args.code) if args.command == "pair" else serve())


if __name__ == "__main__":
    main()
