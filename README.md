# Telegram × Tally AI — Version 1.0

A production-oriented, multi-user connector for one focused job:

> Turn documents from explicitly connected Telegram groups into controlled **Sales, Purchase, Receipt, and Payment** voucher drafts for TallyPrime.

No payroll, reports, returns, reconciliation, master creation, deletion, cancellation, or free-form Tally control is included.

## What Version 1.0 includes

- Telegram OpenID Connect login with PKCE, signed ID-token verification, secure server sessions, and user isolation.
- A native Telegram group picker using a 15-minute, single-use `startgroup` link.
- PDF and image intake from connected groups only.
- Private document storage, SHA-256 duplicate protection, and structured OpenAI extraction.
- Exactly four voucher types with canonical double-entry JSON.
- Owner approval/rejection in Telegram and the web dashboard.
- One exact Tally company per group and explicit default ledger mappings.
- A paired, outbound-only Windows relay—no public Tally port and no desktop UI automation.
- Local ledger validation, preview-first handling, GPT–Tally Connect Pro approvals, execution, and read-back verification.
- D1-backed tenant data and audit events, plus R2-backed source documents.
- Responsive operations dashboard for groups, connectors, queue, and audit trail.

## Architecture

```text
Connected Telegram group
        │  PDF / image
        ▼
Telegram webhook ──► private R2 document
        │
        ├─► structured AI extraction
        ├─► deterministic scope + duplicate checks
        └─► owner review in Telegram/dashboard
                         │ approved canonical JSON only
                         ▼
                  D1 bridge job queue
                         ▲ outbound HTTPS poll
                         │
                Local relay on Tally PC
                         │
                         ├─ exact loaded-company check
                         ├─ local ledger preview
                         └─ GPT–Tally Connect Pro controlled approval/execution
```

The cloud service cannot connect inbound to the user’s computer. The relay also rejects arbitrary XML: it accepts only the canonical voucher contract and passes it through the existing connector’s controls.

## Project layout

```text
web/                 Cloudflare/Sites application, dashboard, APIs, D1 migration
relay.py             Outbound-only local relay for GPT–Tally Connect Pro 1.3+
relay.env.example    Local relay configuration template
setup_telegram.py    Registers the production Telegram webhook
app/                 Tested single-tenant reference service from the first milestone
tests/               Domain and HTTP tests for the reference service
```

## Production setup

### 1. Create the Telegram application

In `@BotFather`:

1. Create or select a bot.
2. Under **Login Widget / Web Login**, register the deployed HTTPS URL.
3. Obtain the OIDC Client ID and Client Secret.
4. Keep the bot token private.
5. Set the bot’s group privacy and administrator requirements as desired; Version 1.0 requests the minimal `manage_chat` administrator right so the bot receives connected-group documents.

### 2. Configure the deployed web app

Copy the values from [web/.dev.vars.example](web/.dev.vars.example) into the deployment’s secret environment. Set `APP_BASE_URL` to the final HTTPS origin with no trailing slash.

The site requires:

- D1 binding `DB`
- R2 binding `FILES`
- the migration in `web/drizzle/0000_massive_nuke.sql`

After deployment, register the webhook:

```powershell
$env:TELEGRAM_BOT_TOKEN = "..."
$env:TELEGRAM_WEBHOOK_SECRET = "..."
python setup_telegram.py https://your-production-origin
```

### 3. Pair the Tally computer

Keep TallyPrime and **GPT–Tally Connect Pro 1.3+** running locally. In the dashboard, choose **Pair Tally desktop** and create a one-time code.

Copy `relay.env.example` values into secure machine-level environment variables. Then:

```powershell
python relay.py pair YOUR-PAIR-CODE
python relay.py run
```

For fully automatic post-after-Telegram-approval, configure separate local Maker, Checker, and Executor users. If live posting or maker–checker credentials are not enabled locally, Version 1.0 safely stages the approval in the local control centre instead of bypassing it.

### 4. Connect a group

1. Log in to the dashboard using the Telegram account that owns the workflow.
2. Choose **Connect Telegram group**.
3. Select the exact group in Telegram.
4. Pair the group with an online connector and the exact company name reported by Tally.
5. Enter the exact default Sales, Purchase, Receipt bank/cash, and Payment bank/cash ledger names.
6. Send a PDF or image and review the draft.

## Safety defaults

- Posting stays disabled until enabled inside GPT–Tally Connect Pro for an exact tested company.
- Company names must match the connector’s live company list exactly.
- Ledger preview runs locally against Tally before an approval request is staged.
- Direct legacy posting, arbitrary Tally XML, ledger creation, Alter beyond the controlled connector policy, deletion, and cancellation are not used.
- One-time group links, pairing codes, session tokens, connector tokens, and job leases are stored only as hashes.
- The owner—not another group member—must approve or reject a draft.

## Verify the build

```powershell
# Reference Python service
python -m pytest
python -m py_compile relay.py setup_telegram.py

# Cloud application (Node 22.13+ and pnpm)
cd web
pnpm install --frozen-lockfile
pnpm exec tsc --noEmit
pnpm lint
pnpm test
```

## Operational limits

- Version 1.0 accepts PDF and image files up to 20 MB.
- One document must contain one voucher.
- Extracted values are suggestions until owner approval.
- Existing Tally ledgers are required; Version 1.0 never silently creates masters.
- Keep the local relay token file private. Re-pair the computer if the token is suspected to be exposed.
