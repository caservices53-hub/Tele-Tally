# GPT‑Tally Connect Pro V2 — Operational Core

V2 is a **local-first staged bulk-entry engine** for TallyPrime. It is intentionally different from the old “one chat tool call = one voucher” connector.

## What works in this bundle

- Connect to TallyPrime through the official XML/HTTP gateway.
- Read the open/configured company, ledger list, stock list and Day Book history.
- Study previous vouchers and persist company-specific accounting patterns in SQLite.
- Import `.csv`, `.xlsx`, `.xlsm`, or JSON transaction batches.
- Accept fully explicit debit/credit rows or full `entries_json`/`items_json` vouchers.
- Resolve known counterparties from verified rules or repeated historical Tally patterns.
- Put unknown/new transaction types into an exception queue instead of guessing.
- Teach a new pattern once and reclassify similar rows in the same job.
- Require a clean review queue before approval.
- Company guard before posting.
- Ledger preflight before posting.
- Bulk XML posting with **recursive failure isolation**: a bad voucher does not force every good voucher to be resent one-by-one.
- Duplicate detection inside the upload and against the existing Tally Day Book.
- Local audit trail in SQLite.
- Optional OpenAI API fallback for unresolved ledger selection. It can only choose from existing Tally ledgers and remains review-only by default.
- MCP tools for a supported remote/custom MCP environment.
- Command-line interface so the engine remains usable even when ChatGPT MCP write access is unavailable.

## Important boundary

This V2 core is production-oriented, but no software can be truthfully declared live-tested against *your* Tally data from this environment because your TallyPrime instance is not available here. Automated unit tests validate the engine, learning flow, safety flow, XML generation, result parsing, and batch failure isolation. The final live acceptance test must be run against a backed-up test company on your PC.

## 1. Tally setup

In TallyPrime enable the HTTP server and use port `9000` (or set `TALLY_URL` to your chosen port). Keep the target company loaded. For safest operation set `TALLY_COMPANY` to the exact company name.

## 2. Install on Windows

Double-click:

`scripts\install_windows.bat`

or in PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -e ".[all]"
```

Recommended environment variables:

```text
TALLY_URL=http://localhost:9000
TALLY_COMPANY=Exact Company Name
GPT_TALLY_DEFAULT_BANK_LEDGER=Exact Bank Ledger Name
```

## 3. Test connection

```bat
scripts\run_cli.bat status
```

## 4. Study previous accounting

Use a meaningful historical period with correctly-entered vouchers:

```bat
scripts\run_cli.bat study 2026-04-01 2026-08-31
```

The engine reads Day Book history and learns repeated company-specific templates. A one-off observation is deliberately not treated as sufficiently reliable for auto-posting. Repeated history or a user-verified teaching rule can become auto-ready.

## 5. Create a bulk job

```bat
scripts\run_cli.bat create-job samples\bulk_payments.csv --company "Exact Company Name"
```

Supported common column names include:

- date
- voucher type
- party/customer/supplier/vendor
- amount
- bank ledger
- party ledger
- reference/invoice no/bill no
- narration/description/particulars
- debit ledger + credit ledger
- entries_json
- items_json

### Three entry modes

**A. Explicit two-ledger row**

`date, voucher_type, amount, debit_ledger, credit_ledger`

This requires no AI inference.

**B. Learned row**

`date, voucher_type, party, amount, bank_ledger`

The engine looks for verified/history patterns.

**C. Full voucher JSON**

Use `entries_json` and optional `items_json` for tax lines, bill allocations, itemized sales/purchases, and complex vouchers. The voucher still passes balance validation and ledger preflight.

## 6. Preview and review exceptions

Preview everything that the engine proposes to post:

```bat
scripts\run_cli.bat preview JOB_ID
```

Then show only unresolved rows:

```bat
scripts\run_cli.bat exceptions JOB_ID
```

An unknown transaction stays `needs_review`. That is intentional.

## 7. Teach a new pattern once

Example: teach `Landlord` Payment as Rent Dr / HDFC Bank Cr:

```bat
scripts\run_cli.bat teach JOB_ID ROW_ID "[{\"ledger\":\"Rent\",\"amount\":100},{\"ledger\":\"HDFC Bank\",\"amount\":-100}]" --bank-ledger "HDFC Bank"
```

The amounts are used as a ratio template; the next transaction can be ₹25,000 or another amount and the template scales automatically.

For a GST invoice, teach the complete ledger split (party, sales/purchase, CGST/SGST/IGST, round-off if applicable). The engine then preserves that observed ratio pattern. Do not use this to override professional GST judgment when the tax treatment actually differs.

## 8. Approve

```bat
scripts\run_cli.bat approve JOB_ID
```

Approval is blocked while unresolved or failed rows remain.

## 9. Post to Tally

Take a Tally backup first. Then:

```bat
scripts\run_cli.bat post JOB_ID --confirm-company "Exact Company Name"
```

The engine:

1. checks the company again,
2. validates ledgers,
3. posts in configured batches,
4. if a batch fails, recursively splits it to isolate the offending voucher,
5. records every result in SQLite.

## MCP tools

`gpt_tally_v2.mcp_server` exposes:

- `tally_status`
- `study_company`
- `create_import_job`
- `create_import_job_from_json`
- `get_job_summary`
- `get_job_exceptions`
- `get_job_preview`
- `teach_mapping`
- `approve_job`
- `post_job`
- `list_learned_rules`

`stdio` mode is useful for MCP clients that can launch local servers. `http` mode binds to `127.0.0.1` and requires `TALLY_MCP_TOKEN`.

Current ChatGPT custom MCP support does not directly attach to arbitrary local MCP servers; use an approved remote/tunnel architecture where available. The accounting engine itself does not depend on that integration and can be operated through the CLI immediately.

## Optional OpenAI classifier

Set both:

```text
OPENAI_API_KEY=...
OPENAI_MODEL=<model available to your API account>
```

When deterministic learning cannot resolve a row, the optional classifier may propose **one of the existing Tally ledgers**. It does not create invented ledgers. By default the row remains subject to the confidence/review workflow. API billing is separate from a ChatGPT subscription.

## Safety rules built into V2

- Never auto-learn from its own unverified prediction.
- User teaching rules are `verified` and outrank historical inference.
- Historical inference needs repeat evidence before it reaches the auto-ready threshold.
- Fuzzy name matches are capped below the default auto threshold.
- Unknown patterns are exceptions, not “Miscellaneous Expense”.
- Company mismatch blocks posting.
- Missing ledgers block the affected row.
- Voucher must balance before XML is generated.

## Run tests

```bat
.venv\Scripts\python -m unittest discover -s tests -v
```

## Data files

By default the SQLite database is:

`data/gpt_tally_v2.sqlite3`

Back this file up with your normal application backups. It contains learned rules, job staging, and audit history.
