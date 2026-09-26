"use client";

import { ChangeEvent, useEffect, useState } from "react";

type Requirement = {
  id: string;
  title: string;
  user_story?: string;
  acceptance_criteria?: string[];
  cases?: TestCase[];
  target?: { application_url?: string; authentication_type?: string; browser?: string; headless?: boolean } | null;
  locators?: Array<{ element: string; validated: boolean }>;
};

type TestCase = { id: string; title: string; status: string; test_type?: string; steps?: Array<{ action: string }> };
type Dashboard = { requirements: number; test_cases: number; results: number; status_counts: Record<string, number> };
type TargetPayload = { application_url: string; authentication_type: string; browser: string; headless: boolean; username_label: string; password_label: string; submit_label: string; guidance: string };

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers: { ...(options?.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...options?.headers }, cache: "no-store" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail ?? "The request could not be completed.");
  return payload as T;
}

export default function Home() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [selected, setSelected] = useState<Requirement | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyLabel, setBusyLabel] = useState("");
  const [targetUrl, setTargetUrl] = useState("");
  const [authenticationType, setAuthenticationType] = useState("No Authentication");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [usernameLabel, setUsernameLabel] = useState("");
  const [passwordLabel, setPasswordLabel] = useState("");
  const [submitLabel, setSubmitLabel] = useState("");
  const [guidance, setGuidance] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh(selectedId?: string) {
    const [summary, items] = await Promise.all([api<Dashboard>("/api/dashboard"), api<Requirement[]>("/api/requirements")]);
    setDashboard(summary);
    setRequirements(items);
    const nextId = selectedId ?? selected?.id ?? items[0]?.id;
    if (nextId) {
      const next = await api<Requirement>(`/api/requirements/${nextId}`);
      setSelected(next);
      setTargetUrl(next.target?.application_url ?? "");
      setAuthenticationType(next.target?.authentication_type ?? "No Authentication");
    }
    else setSelected(null);
  }

  useEffect(() => { refresh().catch((reason: Error) => setError(reason.message)); }, []);

  async function upload(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy(true); setBusyLabel("Analyzing requirement..."); setError(""); setNotice("");
    try {
      const body = new FormData(); body.append("files", file);
      const result = await api<{ requirement: Requirement }>("/api/requirements/analyze", { method: "POST", body });
      setNotice("Requirement analyzed and added to the workspace.");
      setFile(null);
      await refresh(result.requirement.id);
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); setBusyLabel(""); }
  }

  async function generate() {
    if (!selected) return;
    setBusy(true); setBusyLabel("Generating reviewable cases..."); setError("");
    try { await api(`/api/requirements/${selected.id}/generate`, { method: "POST" }); setNotice("Draft cases generated. Review them before automation."); await refresh(selected.id); }
    catch (reason) { setError((reason as Error).message); } finally { setBusy(false); setBusyLabel(""); }
  }

  function targetPayload(): TargetPayload { return { application_url: targetUrl.trim(), authentication_type: authenticationType, browser: "chromium", headless: true, username_label: usernameLabel.trim(), password_label: passwordLabel.trim(), submit_label: submitLabel.trim(), guidance: guidance.trim() }; }

  async function discover() {
    if (!selected) return;
    setBusy(true); setBusyLabel("Inspecting the live page and validating locators..."); setError("");
    try {
      const credentials = authenticationType === "Username & Password" ? { username: username.trim(), password } : undefined;
      await api(`/api/requirements/${selected.id}/discover`, { method: "POST", body: JSON.stringify({ target: targetPayload(), credentials }) });
      setNotice("Shared locators discovered and saved for this story."); await refresh(selected.id);
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); setBusyLabel(""); }
  }

  async function execute(item: TestCase) {
    if (!selected) return;
    setBusy(true); setBusyLabel(`Running ${item.id} in an isolated browser...`); setError("");
    try {
      const credentials = authenticationType === "Username & Password" ? { username: username.trim(), password } : undefined;
      await api(`/api/cases/${item.id}/execute`, { method: "POST", body: JSON.stringify({ case_id: item.id, credentials }) });
      setNotice(`${item.id} completed. Inspect the run history for step evidence.`); await refresh(selected.id);
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); setBusyLabel(""); }
  }

  function choose(event: ChangeEvent<HTMLSelectElement>) { const id = event.target.value; setError(""); api<Requirement>(`/api/requirements/${id}`).then((next) => { setSelected(next); setTargetUrl(next.target?.application_url ?? ""); setAuthenticationType(next.target?.authentication_type ?? "No Authentication"); }).catch((reason: Error) => setError(reason.message)); }

  return <main className="shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">FQ</span><div><strong>Fieldnotes</strong><small>QA workbench</small></div></div>
      <nav><a className="active" href="#overview">Overview</a><a href="#requirements">Requirements</a><a href="#cases">Test cases</a><a href="#runs">Runs and evidence</a></nav>
      <div className="sidebar-foot"><span className="status-dot" /> API connected<div>Production workspace</div></div>
    </aside>
    <section className="content">
      <header className="topbar"><div><p className="eyebrow">Automation workspace / 01</p><h1>Make quality visible.</h1><p className="lede">Turn product stories into reviewed, traceable browser evidence.</p></div><div className="topbar-actions"><span className="env-pill">LOCAL / API</span><button className="avatar" aria-label="Workspace account">FN</button></div></header>
      {busy && <div className="loading-banner" role="status"><span className="loader" />{busyLabel || "Working..."}</div>}{error && <div className="alert error">{error}</div>}{notice && <div className="alert success">{notice}</div>}
      <section id="overview" className="metrics"><Metric label="Requirements" value={dashboard?.requirements ?? 0} detail="source stories" /><Metric label="Test cases" value={dashboard?.test_cases ?? 0} detail="reviewable drafts" /><Metric label="Executed" value={dashboard?.results ?? 0} detail="persisted outcomes" /><Metric label="Pass rate" value={dashboard?.results ? `${Math.round(((dashboard.status_counts.PASS ?? 0) / dashboard.results) * 100)}%` : "--"} detail="from recorded runs" /></section>
      <div className="work-grid">
        <section id="requirements" className="panel upload-panel"><div className="section-heading"><div><p className="eyebrow">Start with source</p><h2>Bring in a requirement</h2></div><span className="step">01</span></div><p className="muted">Upload a story or acceptance criteria. Credentials are extracted locally and never sent to the language model.</p><form onSubmit={upload}><label className="dropzone"><input type="file" accept=".txt,.md,.markdown,.pdf,.docx,.csv,.xlsx" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /> <span className="upload-symbol">+</span><strong>{file ? file.name : "Choose a requirement file"}</strong><small>{file ? "Ready to analyze" : "TXT, MD, PDF, DOCX, CSV, or XLSX"}</small></label><button className="primary" disabled={!file || busy}>{busy ? "Working..." : "Analyze requirement"}</button></form></section>
        <section className="panel focus-panel"><div className="section-heading"><div><p className="eyebrow">Selected story</p><h2>{selected?.title ?? "Nothing selected"}</h2></div><span className="step lime">02</span></div><select className="story-select" value={selected?.id ?? ""} onChange={choose}><option value="" disabled>Select a requirement</option>{requirements.map((item) => <option key={item.id} value={item.id}>{item.id} / {item.title}</option>)}</select>{selected ? <><p className="story">{selected.user_story || "No user story supplied."}</p><div className="target-form"><label>Application URL<input value={targetUrl} onChange={(event) => setTargetUrl(event.target.value)} placeholder="https://qa.example.com" /></label><label>Authentication<select value={authenticationType} onChange={(event) => setAuthenticationType(event.target.value)}><option>No Authentication</option><option>Username &amp; Password</option></select></label>{authenticationType === "Username & Password" && <div className="credential-grid"><label>Username<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" /></label><label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></label><label>Username field label<input value={usernameLabel} onChange={(event) => setUsernameLabel(event.target.value)} placeholder="Optional" /></label><label>Password field label<input value={passwordLabel} onChange={(event) => setPasswordLabel(event.target.value)} placeholder="Optional" /></label><label>Submit button label<input value={submitLabel} onChange={(event) => setSubmitLabel(event.target.value)} placeholder="Optional" /></label></div>}<label>Discovery guidance<textarea value={guidance} onChange={(event) => setGuidance(event.target.value)} placeholder="Optional: focus on account access and primary actions." /></label></div><div className="button-row"><button className="secondary" onClick={discover} disabled={busy || !targetUrl.trim()}>{busy && busyLabel.startsWith("Inspecting") ? "Inspecting..." : "Find and validate elements"}<span>-&gt;</span></button><button className="text-button" onClick={generate} disabled={busy}>Generate cases</button></div></> : <div className="empty">Upload a requirement to begin the workflow.</div>}</section>
      </div>
      <section id="cases" className="panel cases-panel"><div className="section-heading"><div><p className="eyebrow">Review before running</p><h2>Test cases</h2></div><span className="case-count">{selected?.cases?.length ?? 0} in selected story</span></div>{selected?.cases?.length ? <div className="case-list">{selected.cases.map((item) => <article className="case-row" key={item.id}><span className={`case-status ${item.status.toLowerCase()}`}>{item.status}</span><div><strong>{item.title}</strong><small>{item.id} / {item.test_type ?? "Functional"} / {item.steps?.length ?? 0} steps</small></div>{item.status === "Approved" && <button className="row-action execute-action" onClick={() => execute(item)} disabled={busy}>Run</button>}<button className="row-action" aria-label={`Open ${item.title}`}>-&gt;</button></article>)}</div> : <div className="empty wide">Generated cases will appear here for review and approval before script generation or execution.</div>}</section>
      <footer id="runs"><span>Fieldnotes QA / API v1.0</span><span>Streamlit remains available locally at <code>app.py</code> for functional validation.</span></footer>
    </section>
  </main>;
}

function Metric({ label, value, detail }: { label: string; value: string | number; detail: string }) { return <div className="metric"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>; }