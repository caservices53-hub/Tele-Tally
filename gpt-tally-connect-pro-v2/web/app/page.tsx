"use client";

import { ChangeEvent, useEffect, useMemo, useState } from "react";
import * as XLSX from "xlsx";

type JsonObject = Record<string, unknown>;
type JobSummary = { job_id: string; company: string; source: string; status: string; approved: boolean; total: number; counts: Record<string, number> };
type PreviewRow = { row_id: number; source_row: number; status: string; confidence: number; reason: string; source: JsonObject; voucher: JsonObject | null; tally_result: string };
type BridgeStatus = { ok: boolean; bridge_version?: string; tally_url?: string; company?: string; configured_company?: string; error?: string };

const defaultBridge = "http://127.0.0.1:8788";

export default function Home() {
  const [bridgeUrl, setBridgeUrl] = useState(defaultBridge);
  const [token, setToken] = useState("");
  const [status, setStatus] = useState<BridgeStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Start the local bridge, then connect this dashboard.");
  const [fromDate, setFromDate] = useState(new Date(new Date().getFullYear(), 3, 1).toISOString().slice(0, 10));
  const [toDate, setToDate] = useState(new Date().toISOString().slice(0, 10));
  const [job, setJob] = useState<JobSummary | null>(null);
  const [preview, setPreview] = useState<PreviewRow[]>([]);
  const [teachRow, setTeachRow] = useState<number | null>(null);
  const [teachEntries, setTeachEntries] = useState('[\n  {"ledger":"Expense Ledger","amount":1000},\n  {"ledger":"Bank Ledger","amount":-1000}\n]');

  useEffect(() => {
    setBridgeUrl(localStorage.getItem("gptTallyBridgeUrl") || defaultBridge);
    setToken(localStorage.getItem("gptTallyBridgeToken") || "");
  }, []);

  const readyCount = useMemo(() => job?.counts?.ready || 0, [job]);
  const exceptionCount = useMemo(() => (job?.counts?.needs_review || 0) + (job?.counts?.failed || 0), [job]);

  async function localFetch(path: string, init: RequestInit = {}) {
    const headers = new Headers(init.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    const opts = { ...init, headers, cache: "no-store", targetAddressSpace: "loopback" } as RequestInit & { targetAddressSpace: "loopback" };
    const response = await fetch(`${bridgeUrl.replace(/\/$/, "")}${path}`, opts);
    const data = await response.json().catch(() => ({ ok: false, error: `HTTP ${response.status}` }));
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function persistPairing() {
    localStorage.setItem("gptTallyBridgeUrl", bridgeUrl);
    localStorage.setItem("gptTallyBridgeToken", token);
  }

  async function connect() {
    setBusy(true);
    try {
      persistPairing();
      const data = await localFetch("/api/status");
      setStatus(data);
      setMessage(`Connected to Tally company: ${data.company || "Unknown"}`);
    } catch (error) {
      setStatus({ ok: false, error: error instanceof Error ? error.message : String(error) });
      setMessage(`Connection failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally { setBusy(false); }
  }

  async function study() {
    setBusy(true);
    try {
      const data = await localFetch("/api/study", { method: "POST", body: JSON.stringify({ from_date: fromDate, to_date: toDate }) });
      setMessage(`Study complete: ${data.result.rules} learned rules from previous Tally entries.`);
    } catch (error) { setMessage(`Study failed: ${error instanceof Error ? error.message : String(error)}`); }
    finally { setBusy(false); }
  }

  async function parseFile(file: File): Promise<JsonObject[]> {
    const lower = file.name.toLowerCase();
    if (lower.endsWith(".json")) {
      const parsed = JSON.parse(await file.text());
      if (!Array.isArray(parsed)) throw new Error("JSON file must contain a top-level array of transactions.");
      return parsed as JsonObject[];
    }
    if (lower.endsWith(".csv")) {
      const wb = XLSX.read(await file.text(), { type: "string" });
      return XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { defval: "" }) as JsonObject[];
    }
    if (lower.endsWith(".xlsx") || lower.endsWith(".xls")) {
      const wb = XLSX.read(await file.arrayBuffer(), { type: "array", cellDates: false });
      return XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { defval: "" }) as JsonObject[];
    }
    throw new Error("Use CSV, XLSX, XLS, or JSON files.");
  }

  async function importFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    try {
      const rows = await parseFile(file);
      setMessage(`Parsed ${rows.length.toLocaleString()} rows locally. Creating staged job...`);
      const data = await localFetch("/api/jobs", { method: "POST", body: JSON.stringify({ rows, source_name: file.name }) });
      setJob(data.summary);
      setPreview([]);
      await refreshJob(data.job_id);
      setMessage(`Job ${data.job_id} created. ${data.summary.counts.ready || 0} ready; ${data.summary.counts.needs_review || 0} need review.`);
    } catch (error) { setMessage(`Import failed: ${error instanceof Error ? error.message : String(error)}`); }
    finally { setBusy(false); event.target.value = ""; }
  }

  async function refreshJob(jobId = job?.job_id) {
    if (!jobId) return;
    const [summaryData, previewData] = await Promise.all([
      localFetch(`/api/jobs/${jobId}/summary`),
      localFetch(`/api/jobs/${jobId}/preview?limit=1000`),
    ]);
    setJob(summaryData.summary);
    setPreview(previewData.rows);
  }

  async function teach() {
    if (!job || teachRow == null) return;
    setBusy(true);
    try {
      const entries = JSON.parse(teachEntries);
      await localFetch(`/api/jobs/${job.job_id}/teach`, { method: "POST", body: JSON.stringify({ row_id: teachRow, entries, apply_to_similar: true }) });
      await refreshJob();
      setTeachRow(null);
      setMessage("Mapping saved. Similar unresolved rows were reclassified using your verified rule.");
    } catch (error) { setMessage(`Teaching failed: ${error instanceof Error ? error.message : String(error)}`); }
    finally { setBusy(false); }
  }

  async function approve() {
    if (!job) return;
    setBusy(true);
    try {
      await localFetch(`/api/jobs/${job.job_id}/approve`, { method: "POST", body: "{}" });
      await refreshJob();
      setMessage("Job approved locally. Nothing has been posted yet.");
    } catch (error) { setMessage(`Approval blocked: ${error instanceof Error ? error.message : String(error)}`); }
    finally { setBusy(false); }
  }

  async function post() {
    if (!job || !status?.company) return;
    if (!window.confirm(`Post approved job ${job.job_id} to EXACT company "${status.company}"? This writes to TallyPrime.`)) return;
    setBusy(true);
    try {
      const data = await localFetch(`/api/jobs/${job.job_id}/post`, { method: "POST", body: JSON.stringify({ confirm_company: status.company }) });
      await refreshJob();
      setMessage(`Posting completed. ${JSON.stringify(data.result)}`);
    } catch (error) { setMessage(`Posting failed or was blocked: ${error instanceof Error ? error.message : String(error)}`); }
    finally { setBusy(false); }
  }

  return (
    <main>
      <section className="hero">
        <div><span className="eyebrow">LOCAL-FIRST AI ACCOUNTING</span><h1>GPT-Tally Connect Pro <strong>V2</strong></h1><p>Hosted control centre. Accounting engine, learning memory, source files and TallyPrime remain on your Windows PC.</p></div>
        <div className={`status ${status?.ok ? "online" : "offline"}`}>{status?.ok ? "Tally connected" : "Local bridge offline"}</div>
      </section>

      <section className="notice"><b>Security model:</b> this website does not connect to Tally over the public internet. Your browser talks to the authenticated bridge on <code>127.0.0.1</code>; you may be asked to allow Local Network Access.</section>

      <section className="grid two">
        <div className="card">
          <h2>1. Connect local Tally</h2>
          <label>Local bridge URL<input value={bridgeUrl} onChange={e => setBridgeUrl(e.target.value)} /></label>
          <label>Pairing token<input type="password" value={token} onChange={e => setToken(e.target.value)} placeholder="Token shown by configure_windows.bat" /></label>
          <button onClick={connect} disabled={busy || !token}>Connect</button>
          {status?.ok && <dl><dt>Company</dt><dd>{status.company}</dd><dt>Tally endpoint</dt><dd>{status.tally_url}</dd><dt>Bridge</dt><dd>v{status.bridge_version}</dd></dl>}
        </div>
        <div className="card">
          <h2>2. Learn company history</h2>
          <div className="dates"><label>From<input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)} /></label><label>To<input type="date" value={toDate} onChange={e => setToDate(e.target.value)} /></label></div>
          <button onClick={study} disabled={busy || !status?.ok}>Study previous Tally entries</button>
          <p className="hint">Verified recurring patterns become company-specific learning rules in the local SQLite memory.</p>
        </div>
      </section>

      <section className="card">
        <h2>3. Create bulk import job</h2>
        <div className="upload"><input type="file" accept=".csv,.xlsx,.xls,.json" onChange={importFile} disabled={busy || !status?.ok} /><span>Files are parsed in your browser and sent directly to the local bridge.</span></div>
        <p className="hint">Recommended columns: voucher_type, date, party, amount, narration, reference, debit_ledger, credit_ledger, entries_json, items_json.</p>
      </section>

      {job && <>
        <section className="metrics"><div><span>Total rows</span><b>{job.total}</b></div><div><span>Ready</span><b>{readyCount}</b></div><div><span>Need review</span><b>{exceptionCount}</b></div><div><span>Status</span><b>{job.status}</b></div></section>
        <section className="card">
          <div className="row"><div><h2>4. Review & approve</h2><p className="hint">Job: {job.job_id} · Source: {job.source}</p></div><button className="secondary" onClick={() => refreshJob()} disabled={busy}>Refresh</button></div>
          <div className="tableWrap"><table><thead><tr><th>Row</th><th>Status</th><th>Confidence</th><th>Reason</th><th>Source</th><th>Action</th></tr></thead><tbody>{preview.map(r => <tr key={r.row_id}><td>{r.source_row}</td><td><span className={`pill ${r.status}`}>{r.status}</span></td><td>{Math.round((r.confidence || 0) * 100)}%</td><td>{r.reason}</td><td><code>{JSON.stringify(r.source)}</code></td><td>{r.status === "needs_review" || r.status === "failed" ? <button className="small" onClick={() => { setTeachRow(r.row_id); const amount = Number(r.source.amount || 0); setTeachEntries(JSON.stringify([{ ledger: "Expense Ledger", amount }, { ledger: "Bank Ledger", amount: -amount }], null, 2)); }}>Teach</button> : "—"}</td></tr>)}</tbody></table></div>
          <div className="actions"><button onClick={approve} disabled={busy || exceptionCount > 0 || job.approved}>{job.approved ? "Approved" : "Approve job"}</button><button className="danger" onClick={post} disabled={busy || !job.approved || !status?.company}>Post approved job to Tally</button></div>
        </section>
      </>}

      {teachRow != null && <div className="modalBackdrop"><div className="modal"><h2>Teach this new accounting pattern</h2><p>Enter balanced ledger legs. This verified mapping will be stored locally and applied to similar future transactions.</p><textarea value={teachEntries} onChange={e => setTeachEntries(e.target.value)} rows={10} /><div className="actions"><button className="secondary" onClick={() => setTeachRow(null)}>Cancel</button><button onClick={teach} disabled={busy}>Save rule & reclassify</button></div></div></div>}
      <div className="toast">{busy ? "Working… " : ""}{message}</div>
    </main>
  );
}
