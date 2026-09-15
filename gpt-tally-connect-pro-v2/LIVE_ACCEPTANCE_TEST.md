# Live acceptance test against your TallyPrime

The automated tests in this bundle run without touching your books. Before the first real write, use a **backup/test company**.

## A. Connectivity (read only)

1. Open TallyPrime.
2. Load the target test company.
3. Enable HTTP server on port 9000.
4. Set `TALLY_COMPANY` to the exact test-company name.
5. Run:

```bat
scripts\run_cli.bat status
```

Expected: the company name and URL are returned without an error.

## B. Learn history (read only)

Use a period containing correctly-entered examples:

```bat
scripts\run_cli.bat study 2026-04-01 2026-08-31
```

Expected: ledger count, voucher count, learned pattern count and rule count are greater than zero for an active company.

## C. Stage one explicit voucher (no Tally write yet)

Edit `samples/explicit_entries.csv` so `Rent` and `Cash` match exact ledger names in your test company. Then:

```bat
scripts\run_cli.bat create-job samples\explicit_entries.csv --company "YOUR TEST COMPANY"
scripts\run_cli.bat preview JOB_ID
```

Expected: row status is `ready` and the debit/credit values are exactly what you supplied.

## D. Approval

```bat
scripts\run_cli.bat approve JOB_ID
```

Expected: job becomes `approved`.

## E. First write

Take a Tally backup immediately before this step.

```bat
scripts\run_cli.bat post JOB_ID --confirm-company "YOUR TEST COMPANY"
```

Expected: row status becomes `posted`. Open Day Book in Tally and verify date, voucher type, ledgers, amount, reference and narration.

## F. Learning test

Create a file such as:

```csv
date,voucher type,party,amount,bank ledger,reference,narration
2026-09-01,Payment,My Monthly Rent,25000,HDFC Bank,SEP-RENT,September rent
```

The first occurrence should remain `needs_review` unless a sufficiently strong historical match exists. Teach it once using the exact Tally entries. Create another job with the same party/pattern and a different amount. Expected: it becomes `ready` from the verified rule and scales the entry amounts.

## G. Failure isolation test (optional)

In a test-only job, deliberately use one invalid ledger among several valid rows. Expected: the invalid row is stopped by preflight or fails individually; valid rows remain postable. Do not run deliberate-failure tests in live books.
