"use client";

import "./workbench.css";
import React, { ChangeEvent, FormEvent, useEffect, useState } from "react";

// Types
type Step = {
  number?: number;
  step_number?: number;
  action: string;
  test_data?: string;
  expected?: string;
  expected_result?: string;
  actual?: string;
  status?: string;
  duration?: number;
  locator?: string;
  locator_requirement?: string;
  error?: string;
  screenshot_path?: string;
  before_screenshot_path?: string;
  page_url?: string;
  page_title?: string;
};

type TestCase = {
  id: string;
  requirement_id: string;
  title: string;
  test_type: string;
  priority: string;
  status: string;
  steps: Step[];
  preconditions?: string[];
  test_data?: string | Record<string, unknown>;
  expected_results?: string[];
  generation_note?: string;
  [key: string]: unknown;
};

type Target = {
  requirement_id?: string;
  application_url: string;
  authentication_type: string;
  browser: string;
  headless: boolean;
  username_label: string;
  password_label: string;
  submit_label: string;
  guidance: string;
};

type LocatorCandidate = {
  kind: string;
  value: string;
  valid: boolean;
  count?: number;
  reason?: string;
};

type Locator = {
  id?: string;
  element: string;
  tag: string;
  xpath: string;
  validated: boolean;
  confidence: number;
  candidates: LocatorCandidate[];
  guidance_matches?: string[];
  explanation?: string;
  page_url?: string;
};

type Run = {
  id: string;
  started_at: string;
  finished_at?: string;
  status: string;
  browser: string;
  environment: string;
  summary: Record<string, number>;
};

type TestResult = {
  id?: string;
  run_id: string;
  test_case_id: string;
  title?: string;
  requirement_id?: string;
  priority?: string;
  test_type?: string;
  status: string;
  duration: number;
  error?: string;
  browser?: string;
  run_started_at?: string;
  steps?: Step[];
  details?: Record<string, unknown>;
};

type Suite = {
  id: string;
  name: string;
  description: string;
  case_count: number;
  case_ids: string[];
};

type SettingsView = {
  llm_provider: string;
  llm_base_url?: string;
  llm_model?: string;
  llm_configured: boolean;
  browser: string;
  headless?: boolean;
  timeout_ms: number;
  execution_enabled: boolean;
  storage: string;
  database_path?: string;
  evidence_dir?: string;
};

type Report = {
  runs: Run[];
  results: TestResult[];
  counts: Record<string, number>;
  pass_rate: number;
};

type RuntimeCredentials = {
  username: string;
  password: string;
};

type Requirement = {
  id: string;
  title: string;
  user_story: string;
  acceptance_criteria: string[];
  source_files: string[];
  analysis: Record<string, unknown>;
  target?: Target | null;
  cases?: TestCase[];
  locators?: Locator[];
};

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");

const SECTIONS = [
  "Overview",
  "Requirements",
  "Test case generation",
  "Test cases",
  "Find elements",
  "Script generation",
  "Test execution",
  "Execution history",
  "Reporting",
  "Suites",
  "Settings",
];

const emptyTarget = (url = ""): Target => ({
  application_url: url,
  authentication_type: "No Authentication",
  browser: "chromium",
  headless: true,
  username_label: "",
  password_label: "",
  submit_label: "",
  guidance: "",
});

const STORAGE_KEY = "fieldnotes_qa_workspace_v1";

type LocalWorkspace = {
  requirements: Requirement[];
  allCases: TestCase[];
  targets: Record<string, Target>;
  locators: Locator[];
};

function getLocalWorkspace(): LocalWorkspace {
  if (typeof window === "undefined") return { requirements: [], allCases: [], targets: {}, locators: [] };
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : { requirements: [], allCases: [], targets: {}, locators: [] };
  } catch {
    return { requirements: [], allCases: [], targets: {}, locators: [] };
  }
}

function updateLocalWorkspace(patch: Partial<LocalWorkspace>) {
  if (typeof window === "undefined") return;
  try {
    const current = getLocalWorkspace();
    const updated: LocalWorkspace = {
      requirements: patch.requirements ?? current.requirements,
      allCases: patch.allCases ?? current.allCases,
      targets: patch.targets ?? current.targets,
      locators: patch.locators ?? current.locators,
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
  } catch {}
}

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  let response = await fetch(url, {
    ...options,
    headers: {
      ...(options?.body instanceof FormData
        ? {}
        : options?.body
        ? { "Content-Type": "application/json" }
        : {}),
      ...options?.headers,
    },
    cache: "no-store",
  });

  // If 404 on serverless instance, auto-sync local workspace to populate container and retry
  if (response.status === 404 && (path.includes("/api/requirements") || path.includes("/api/cases"))) {
    const local = getLocalWorkspace();
    if (local.requirements.length > 0 || local.allCases.length > 0) {
      try {
        await fetch(`${API_BASE}/api/workspace/sync`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            requirements: local.requirements,
            cases: local.allCases,
            targets: Object.values(local.targets),
            locators: local.locators,
          }),
        });
        response = await fetch(url, {
          ...options,
          headers: {
            ...(options?.body instanceof FormData
              ? {}
              : options?.body
              ? { "Content-Type": "application/json" }
              : {}),
            ...options?.headers,
          },
          cache: "no-store",
        });
      } catch {}
    }
  }

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(
      typeof payload.detail === "string"
        ? payload.detail
        : `Request to ${path} failed with status ${response.status}`
    );
  }
  return payload as T;
}

export default function Workbench() {
  const [section, setSection] = useState("Overview");
  const [dashboard, setDashboard] = useState({
    requirements: 0,
    test_cases: 0,
    results: 0,
    status_counts: {} as Record<string, number>,
    recent_runs: [] as Run[],
  });
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [selected, setSelected] = useState<Requirement | null>(null);
  const [allCases, setAllCases] = useState<TestCase[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [suites, setSuites] = useState<Suite[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [credentialsByStory, setCredentialsByStory] = useState<Record<string, RuntimeCredentials>>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [lightboxImage, setLightboxImage] = useState<string | null>(null);

  async function refresh(targetId = selectedId) {
    try {
      const [summary, stories, cases, history, savedSuites, reportData, settingsData] =
        await Promise.all([
          api<typeof dashboard>("/api/dashboard"),
          api<Requirement[]>("/api/requirements"),
          api<TestCase[]>("/api/cases"),
          api<Run[]>("/api/runs"),
          api<Suite[]>("/api/suites"),
          api<Report>("/api/report"),
          api<SettingsView>("/api/settings"),
        ]);

      const local = getLocalWorkspace();
      const storyMap = new Map<string, Requirement>();
      local.requirements.forEach((r) => storyMap.set(r.id, r));
      stories.forEach((r) => storyMap.set(r.id, { ...storyMap.get(r.id), ...r }));
      const mergedStories = Array.from(storyMap.values());

      const caseMap = new Map<string, TestCase>();
      local.allCases.forEach((c) => caseMap.set(c.id, c));
      cases.forEach((c) => caseMap.set(c.id, { ...caseMap.get(c.id), ...c }));
      const mergedCases = Array.from(caseMap.values());

      updateLocalWorkspace({ requirements: mergedStories, allCases: mergedCases });

      setDashboard(summary);
      setRequirements(mergedStories);
      setAllCases(mergedCases);
      setRuns(history);
      setSuites(savedSuites);
      setReport(reportData);
      setSettings(settingsData);

      const nextId = targetId || mergedStories[0]?.id || "";
      setSelectedId(nextId);
      if (nextId) {
        try {
          const fullReq = await api<Requirement>(`/api/requirements/${nextId}`);
          setSelected(fullReq);
          updateLocalWorkspace({
            requirements: [fullReq, ...mergedStories.filter((r) => r.id !== fullReq.id)],
          });
        } catch {
          const cached = mergedStories.find((r) => r.id === nextId);
          if (cached) {
            setSelected(cached);
          }
        }
      } else {
        setSelected(null);
      }
    } catch (err) {
      console.warn("Refresh error:", err);
    }
  }

  useEffect(() => {
    refresh().catch((err: Error) => setError(err.message));
  }, []);

  async function act(label: string, operation: () => Promise<void>) {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await operation();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function chooseStory(event: ChangeEvent<HTMLSelectElement>) {
    const id = event.target.value;
    setSelectedId(id);
    setError("");
    if (!id) {
      setSelected(null);
      return;
    }
    try {
      const fullReq = await api<Requirement>(`/api/requirements/${id}`);
      setSelected(fullReq);
    } catch (reason) {
      setError((reason as Error).message);
    }
  }

  const casesForStory = allCases.filter(
    (item) => !selectedId || item.requirement_id === selectedId
  );

  return (
    <main className="shell">
      {/* Sidebar Navigation */}
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">FQ</span>
          <div className="brand-info">
            <strong>Fieldnotes QA</strong>
            <small>Automation Workbench</small>
          </div>
        </div>

        <nav>
          {SECTIONS.map((item, index) => (
            <button
              key={item}
              className={`nav-item ${section === item ? "active" : ""}`}
              onClick={() => {
                setSection(item);
                setError("");
                setNotice("");
              }}
            >
              <span className="nav-num">{String(index + 1).padStart(2, "0")}</span>
              <span>{item}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div style={{ marginBottom: 6 }}>
            <span
              className={`status-pill ${
                settings?.execution_enabled ? "" : "warning"
              }`}
            >
              <span className="status-dot" />
              {settings?.execution_enabled ? "Worker Ready" : "Serverless / Ephemeral"}
            </span>
          </div>
          <div>Storage: {settings?.storage ?? "Checking..."}</div>
        </div>
      </aside>

      {/* Main Content View */}
      <section className="content">
        <header className="topbar">
          <div>
            <p className="eyebrow">
              Fieldnotes QA / {String(SECTIONS.indexOf(section) + 1).padStart(2, "0")}
            </p>
            <h1>{section === "Overview" ? "Automation Workspace" : section}</h1>
            <p className="lede">
              Move seamlessly from requirements to reviewed cases, locators, scripts, and verified execution evidence.
            </p>
          </div>
          <div className="topbar-actions">
            <span
              className={`worker-badge ${
                settings?.execution_enabled ? "" : "disabled"
              }`}
            >
              {settings?.execution_enabled ? "BROWSER ENGINE READY" : "BROWSER WORKER REQUIRED"}
            </span>
            <button
              className="btn-icon"
              title="Refresh all workspace data"
              onClick={() => act("Refreshing workspace data...", async () => refresh())}
            >
              ↺ Refresh
            </button>
          </div>
        </header>

        {/* Global Story Picker */}
        <div className="story-bar">
          <label htmlFor="global-story-select">Active Story:</label>
          <select
            id="global-story-select"
            value={selectedId}
            onChange={chooseStory}
          >
            <option value="">All Requirements / No Filter</option>
            {requirements.map((req) => (
              <option key={req.id} value={req.id}>
                {req.id} · {req.title}
              </option>
            ))}
          </select>
          <span className="story-meta">
            {requirements.length} stories · {casesForStory.length} cases
          </span>
        </div>

        {/* Global Notifications */}
        {busy && (
          <div className="banner loading">
            <span className="spinner" />
            <span>{busy}</span>
          </div>
        )}
        {error && <div className="banner error">{error}</div>}
        {notice && <div className="banner success">{notice}</div>}

        {/* Sub-Views */}
        {section === "Overview" && (
          <OverviewView
            dashboard={dashboard}
            requirements={requirements}
            cases={allCases}
            runs={runs}
            settings={settings}
            navigate={setSection}
          />
        )}

        {section === "Requirements" && (
          <RequirementsView
            requirements={requirements}
            selected={selected}
            onUpload={(files) =>
              act("Uploading and analyzing requirement documents...", async () => {
                const body = new FormData();
                files.forEach((file) => body.append("files", file));
                const result = await api<{
                  requirement: Requirement;
                  mode: string;
                  session_credentials?: RuntimeCredentials;
                }>("/api/requirements/analyze", { method: "POST", body });
                if (result.session_credentials) {
                  setCredentialsByStory((current) => ({
                    ...current,
                    [result.requirement.id]: result.session_credentials!,
                  }));
                }
                const local = getLocalWorkspace();
                const updatedReqs = [
                  result.requirement,
                  ...local.requirements.filter((r) => r.id !== result.requirement.id),
                ];
                updateLocalWorkspace({ requirements: updatedReqs });
                setRequirements(updatedReqs);
                setSelectedId(result.requirement.id);
                setSelected(result.requirement);
                setNotice(`Requirement successfully analyzed (${result.mode}).`);
                refresh(result.requirement.id).catch(() => {});
              })
            }
            onDelete={() =>
              selected &&
              act("Deleting requirement and all linked artifacts...", async () => {
                await api(`/api/requirements/${selected.id}`, { method: "DELETE" });
                const local = getLocalWorkspace();
                const updatedReqs = local.requirements.filter((r) => r.id !== selected.id);
                const updatedCases = local.allCases.filter((c) => c.requirement_id !== selected.id);
                updateLocalWorkspace({ requirements: updatedReqs, allCases: updatedCases });
                setRequirements(updatedReqs);
                setAllCases(updatedCases);
                setCredentialsByStory((current) => {
                  const copy = { ...current };
                  delete copy[selected.id];
                  return copy;
                });
                setNotice(`Deleted requirement ${selected.id}.`);
                await refresh("");
              })
            }
          />
        )}

        {section === "Test case generation" && (
          <GenerationView
            selected={selected}
            casesForStory={casesForStory}
            onGenerate={() =>
              selected &&
              act("Generating positive, negative and boundary drafts...", async () => {
                const result = await api<{ mode: string; cases: TestCase[] }>(
                  `/api/requirements/${selected.id}/generate`,
                  {
                    method: "POST",
                    body: JSON.stringify({ requirement: selected }),
                  }
                );
                if (result.cases && result.cases.length > 0) {
                  const local = getLocalWorkspace();
                  const updatedCases = [
                    ...result.cases,
                    ...local.allCases.filter((c) => c.requirement_id !== selected.id),
                  ];
                  updateLocalWorkspace({ allCases: updatedCases });
                  setAllCases(updatedCases);
                }
                setNotice(`Draft cases generated (${result.mode}).`);
                refresh(selected.id).catch(() => {});
              })
            }
          />
        )}

        {section === "Test cases" && (
          <TestCasesView
            cases={casesForStory}
            requirements={requirements}
            selectedStoryId={selectedId}
            onUpdate={(item) =>
              act(`Saving test case ${item.id}...`, async () => {
                const local = getLocalWorkspace();
                const updatedCases = local.allCases.map((c) => (c.id === item.id ? item : c));
                updateLocalWorkspace({ allCases: updatedCases });
                setAllCases(updatedCases);
                await api(`/api/cases/${item.id}`, {
                  method: "PUT",
                  body: JSON.stringify(item),
                });
                setNotice(`Case ${item.id} saved.`);
                refresh(selectedId).catch(() => {});
              })
            }
            onDelete={(id) =>
              act(`Deleting test case ${id}...`, async () => {
                await api(`/api/cases/${id}`, { method: "DELETE" });
                const local = getLocalWorkspace();
                const updatedCases = local.allCases.filter((c) => c.id !== id);
                updateLocalWorkspace({ allCases: updatedCases });
                setAllCases(updatedCases);
                setNotice(`Case ${id} deleted.`);
                refresh(selectedId).catch(() => {});
              })
            }
            onRegenerate={(id) =>
              act(`Regenerating test case ${id}...`, async () => {
                const res = await api<{ mode: string; case?: TestCase }>(`/api/cases/${id}/regenerate`, {
                  method: "POST",
                });
                if (res.case) {
                  const local = getLocalWorkspace();
                  const updatedCases = local.allCases.map((c) => (c.id === id ? res.case! : c));
                  updateLocalWorkspace({ allCases: updatedCases });
                  setAllCases(updatedCases);
                }
                setNotice(`Case ${id} regenerated (${res.mode}); approval reset to Draft.`);
                refresh(selectedId).catch(() => {});
              })
            }
          />
        )}

        {section === "Find elements" && (
          <ElementsView
            selected={selected}
            settings={settings}
            credentials={credentialsByStory[selectedId] ?? { username: "", password: "" }}
            onCredentialsChange={(creds) =>
              setCredentialsByStory((current) => ({ ...current, [selectedId]: creds }))
            }
            onSaveTarget={(target) =>
              selected &&
              act("Saving target settings...", async () => {
                const local = getLocalWorkspace();
                const updatedTargets = { ...local.targets, [selected.id]: target };
                updateLocalWorkspace({ targets: updatedTargets });
                if (selected) {
                  setSelected({ ...selected, target });
                }
                await api(`/api/requirements/${selected.id}/target`, {
                  method: "PUT",
                  body: JSON.stringify(target),
                });
                setNotice("Target settings saved for this story.");
                refresh(selected.id).catch(() => {});
              })
            }
            onDiscover={(target, creds) =>
              selected &&
              act("Inspecting live DOM and discovering shared locators...", async () => {
                const result = await api<{ count: number }>(
                  `/api/requirements/${selected.id}/discover`,
                  { method: "POST", body: JSON.stringify({ target, credentials: creds }) }
                );
                if (creds) {
                  setCredentialsByStory((current) => ({
                    ...current,
                    [selected.id]: creds,
                  }));
                }
                setNotice(`Discovered and validated ${result.count} shared elements.`);
                await refresh(selected.id);
              })
            }
          />
        )}

        {section === "Script generation" && (
          <ScriptsView
            cases={casesForStory}
            selected={selected}
            run={act}
            onMessage={setNotice}
          />
        )}

        {section === "Test execution" && (
          <ExecutionView
            cases={casesForStory}
            selected={selected}
            settings={settings}
            credentials={credentialsByStory[selectedId] ?? { username: "", password: "" }}
            onCredentialsChange={(creds) =>
              setCredentialsByStory((current) => ({ ...current, [selectedId]: creds }))
            }
            onExecuteBatch={async (caseIds, creds) => {
              if (!selected) return;
              await act(`Executing ${caseIds.length} approved test cases in browser...`, async () => {
                const res = await api<{ run_id: string; summary: Record<string, number>; outcomes: Step[] }>(
                  "/api/execution/batch",
                  {
                    method: "POST",
                    body: JSON.stringify({
                      case_ids: caseIds,
                      requirement_id: selected.id,
                      credentials: creds,
                    }),
                  }
                );
                setNotice(
                  `Batch execution completed (Run ${res.run_id}). Passed: ${
                    res.summary.PASS ?? 0
                  }, Failed: ${res.summary.FAIL ?? 0}.`
                );
                await refresh(selected.id);
              });
            }}
            onPreviewImage={(src) => setLightboxImage(src)}
          />
        )}

        {section === "Execution history" && (
          <HistoryView
            runs={runs}
            onPreviewImage={(src) => setLightboxImage(src)}
          />
        )}

        {section === "Reporting" && <ReportingView report={report} runs={runs} />}

        {section === "Suites" && (
          <SuitesView
            suites={suites}
            cases={allCases}
            onSave={(suite) =>
              act("Saving test suite...", async () => {
                await api("/api/suites", {
                  method: "POST",
                  body: JSON.stringify(suite),
                });
                setNotice("Test suite saved.");
                await refresh(selectedId);
              })
            }
            onDelete={(id) =>
              act("Deleting test suite...", async () => {
                await api(`/api/suites/${id}`, { method: "DELETE" });
                setNotice("Suite deleted.");
                await refresh(selectedId);
              })
            }
          />
        )}

        {section === "Settings" && (
          <SettingsView
            settings={settings}
            onUpdateSettings={(newSettings) =>
              act("Saving runtime settings...", async () => {
                const updated = await api<SettingsView>("/api/settings", {
                  method: "POST",
                  body: JSON.stringify(newSettings),
                });
                setSettings(updated);
                setNotice("Settings successfully updated.");
              })
            }
          />
        )}

        {/* Full Resolution Screenshot Lightbox */}
        {lightboxImage && (
          <div className="modal-overlay" onClick={() => setLightboxImage(null)}>
            <div className="modal-content" onClick={(e) => e.stopPropagation()}>
              <button
                className="modal-close"
                onClick={() => setLightboxImage(null)}
                aria-label="Close image preview"
              >
                ✕
              </button>
              <img src={lightboxImage} alt="Test execution step evidence" />
            </div>
          </div>
        )}

        <footer>
          <span>
            Fieldnotes QA · Production Platform v1.0
          </span>
          <span>
            Streamlit validation interface preserved at <code>app.py</code>
          </span>
        </footer>
      </section>
    </main>
  );
}

// ==========================================
// 01 / OVERVIEW VIEW
// ==========================================
function OverviewView({
  dashboard,
  requirements,
  cases,
  runs,
  settings,
  navigate,
}: {
  dashboard: {
    requirements: number;
    test_cases: number;
    results: number;
    status_counts: Record<string, number>;
  };
  requirements: Requirement[];
  cases: TestCase[];
  runs: Run[];
  settings: SettingsView | null;
  navigate: (view: string) => void;
}) {
  const pass = dashboard.status_counts.PASS ?? 0;
  const fail = dashboard.status_counts.FAIL ?? 0;
  const blocked = dashboard.status_counts.BLOCKED ?? 0;
  const executed = pass + fail;
  const passRate = executed ? `${Math.round((pass / executed) * 100)}%` : "—";

  return (
    <>
      <div className="metrics-row">
        <div className="metric-card">
          <span>Requirements</span>
          <strong>{dashboard.requirements}</strong>
          <small>{requirements.length} source stories registered</small>
        </div>
        <div className="metric-card">
          <span>Test cases</span>
          <strong>{dashboard.test_cases}</strong>
          <small>
            {cases.filter((c) => c.status === "Approved").length} approved ·{" "}
            {cases.filter((c) => c.status === "Draft").length} drafts
          </small>
        </div>
        <div className="metric-card">
          <span>Executed results</span>
          <strong>{dashboard.results}</strong>
          <small>{runs.length} browser runs recorded</small>
        </div>
        <div className="metric-card">
          <span>Pass rate</span>
          <strong style={{ color: pass >= fail ? "#34d399" : "#fb7185" }}>
            {passRate}
          </strong>
          <small>
            {pass} passed · {fail} failed {blocked ? `· ${blocked} blocked` : ""}
          </small>
        </div>
      </div>

      <div className="workflow-stepper">
        {[
          {
            num: "01",
            title: "Requirements",
            desc: "Upload and analyze source specifications & business rules.",
            target: "Requirements",
          },
          {
            num: "02",
            title: "Find Elements",
            desc: "Discover and validate live DOM locators for the story.",
            target: "Find elements",
          },
          {
            num: "03",
            title: "Review & Scripts",
            desc: "Inspect traceability, approve cases, and generate scripts.",
            target: "Test cases",
          },
          {
            num: "04",
            title: "Execute & Report",
            desc: "Run isolated cases in Playwright and verify visual evidence.",
            target: "Test execution",
          },
        ].map((item) => (
          <div
            key={item.num}
            className="stepper-card"
            onClick={() => navigate(item.target)}
          >
            <div className="stepper-num">{item.num}</div>
            <div className="stepper-title">{item.title}</div>
            <div className="stepper-desc">{item.desc}</div>
          </div>
        ))}
      </div>

      <div className="panel">
        <div className="panel-header">
          <h2>Recent Execution Activity</h2>
          <button className="btn-secondary" onClick={() => navigate("Execution history")}>
            View All Runs →
          </button>
        </div>
        {runs.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Started</th>
                  <th>Status</th>
                  <th>Browser</th>
                  <th>Outcome Summary</th>
                </tr>
              </thead>
              <tbody>
                {runs.slice(0, 6).map((run) => (
                  <tr key={run.id}>
                    <td>
                      <code>{run.id}</code>
                    </td>
                    <td>{new Date(run.started_at).toLocaleString()}</td>
                    <td>
                      <span
                        className={`badge ${
                          run.status === "COMPLETED" ? "badge-pass" : "badge-blocked"
                        }`}
                      >
                        {run.status}
                      </span>
                    </td>
                    <td>{run.browser}</td>
                    <td>
                      {Object.entries(run.summary || {})
                        .map(([k, v]) => `${k}: ${v}`)
                        .join(" · ") || "In progress"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p style={{ color: "var(--text-muted)", fontSize: "0.84rem" }}>
            No execution runs recorded yet. Execute approved cases to populate outcomes.
          </p>
        )}
      </div>

      <div className="panel">
        <div className="panel-header">
          <h2>System Readiness & Configuration</h2>
        </div>
        <div className="grid-3">
          <div className="metric-card" style={{ padding: 14 }}>
            <span>LLM Provider</span>
            <strong style={{ fontSize: "1.2rem", margin: "6px 0" }}>
              {settings?.llm_provider || "offline"}
            </strong>
            <small>
              {settings?.llm_configured
                ? "API Credentials Configured"
                : "Offline Heuristic Draft Mode"}
            </small>
          </div>
          <div className="metric-card" style={{ padding: 14 }}>
            <span>Browser Worker</span>
            <strong style={{ fontSize: "1.2rem", margin: "6px 0" }}>
              {settings?.browser || "chromium"}
            </strong>
            <small>
              {settings?.execution_enabled
                ? "Playwright Execution Enabled"
                : "Worker Required on Serverless"}
            </small>
          </div>
          <div className="metric-card" style={{ padding: 14 }}>
            <span>Database & Storage</span>
            <strong style={{ fontSize: "1.2rem", margin: "6px 0" }}>
              {settings?.storage || "SQLite"}
            </strong>
            <small>{settings?.database_path || "data/automation.db"}</small>
          </div>
        </div>
      </div>
    </>
  );
}

// ==========================================
// 02 / REQUIREMENTS VIEW
// ==========================================
function RequirementsView({
  requirements,
  selected,
  onUpload,
  onDelete,
}: {
  requirements: Requirement[];
  selected: Requirement | null;
  onUpload: (files: File[]) => void;
  onDelete: () => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [confirmDelete, setConfirmDelete] = useState(false);

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    if (e.target.files) {
      setFiles(Array.from(e.target.files));
    }
  }

  const totalBytes = files.reduce((acc, f) => acc + f.size, 0);

  return (
    <div className="grid-2">
      <div className="panel">
        <div className="panel-header">
          <h2>Intake Requirement Documents</h2>
        </div>
        <p style={{ color: "var(--text-dim)", fontSize: "0.84rem", lineHeight: 1.5 }}>
          Upload specifications in PDF, DOCX, XLSX, CSV, TXT, or Markdown. The requirement agent
          extracts the story, acceptance criteria, test data rules, and credentials safely.
        </p>

        <label className="dropzone">
          <input
            type="file"
            multiple
            accept=".pdf,.docx,.xlsx,.csv,.txt,.md,.markdown"
            onChange={handleFileChange}
          />
          <div className="dropzone-icon">↑</div>
          <strong style={{ color: "#fff", fontSize: "0.9rem" }}>
            {files.length ? `${files.length} document(s) chosen` : "Choose or drag requirement files"}
          </strong>
          <small style={{ color: "var(--text-muted)" }}>
            PDF, DOCX, XLSX, CSV, TXT, MD (Max 10 files · Up to 4 MB combined)
          </small>
        </label>

        {files.length > 0 && (
          <div className="file-chips">
            {files.map((f, i) => (
              <span key={i} className="file-chip">
                📄 {f.name} ({(f.size / 1024).toFixed(0)} KB)
              </span>
            ))}
          </div>
        )}

        <button
          className="btn-primary"
          style={{ width: "100%", marginTop: 12 }}
          disabled={!files.length || files.length > 10 || totalBytes > 4 * 1024 * 1024}
          onClick={() => onUpload(files)}
        >
          Analyze Uploaded Documents
        </button>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h2>Requirement Details & Story</h2>
          <span className="badge badge-tag">{selected?.id || "None selected"}</span>
        </div>

        {selected ? (
          <div>
            <div style={{ marginBottom: 16 }}>
              <span style={{ fontSize: "0.76rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
                Title
              </span>
              <h3 style={{ margin: "4px 0 10px", fontSize: "1.1rem", color: "#fff" }}>
                {selected.title}
              </h3>
            </div>

            <div style={{ marginBottom: 16 }}>
              <span style={{ fontSize: "0.76rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
                User Story
              </span>
              <p
                style={{
                  background: "var(--bg-base)",
                  padding: "12px 14px",
                  borderRadius: "var(--radius-md)",
                  border: "1px solid var(--border-subtle)",
                  fontSize: "0.85rem",
                  lineHeight: 1.55,
                  margin: "4px 0",
                  color: "#e2e8f0",
                }}
              >
                {selected.user_story || "No user story provided."}
              </p>
            </div>

            <div style={{ marginBottom: 16 }}>
              <span style={{ fontSize: "0.76rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
                Acceptance Criteria ({selected.acceptance_criteria?.length ?? 0})
              </span>
              <ul
                style={{
                  paddingLeft: 20,
                  fontSize: "0.84rem",
                  color: "#cbd5e1",
                  lineHeight: 1.6,
                  margin: "6px 0",
                }}
              >
                {selected.acceptance_criteria?.map((item, idx) => (
                  <li key={idx}>{item}</li>
                ))}
              </ul>
            </div>

            {selected.source_files?.length > 0 && (
              <div style={{ marginBottom: 20 }}>
                <span style={{ fontSize: "0.74rem", color: "var(--text-muted)" }}>
                  Source Documents: {selected.source_files.join(", ")}
                </span>
              </div>
            )}

            <div
              style={{
                marginTop: 24,
                paddingTop: 16,
                borderTop: "1px solid var(--border-subtle)",
                display: "flex",
                alignItems: "center",
                gap: 12,
              }}
            >
              <label style={{ fontSize: "0.78rem", display: "flex", alignItems: "center", gap: 6 }}>
                <input
                  type="checkbox"
                  checked={confirmDelete}
                  onChange={(e) => setConfirmDelete(e.target.checked)}
                />
                Confirm deletion of story and dependent cases
              </label>
              <button
                className="btn-danger"
                disabled={!confirmDelete}
                onClick={onDelete}
              >
                Delete Requirement
              </button>
            </div>
          </div>
        ) : (
          <p style={{ color: "var(--text-muted)", fontSize: "0.84rem" }}>
            Select or upload a requirement to view acceptance criteria and stories.
          </p>
        )}
      </div>
    </div>
  );
}

// ==========================================
// 03 / TEST CASE GENERATION VIEW
// ==========================================
function GenerationView({
  selected,
  casesForStory,
  onGenerate,
}: {
  selected: Requirement | null;
  casesForStory: TestCase[];
  onGenerate: () => void;
}) {
  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Generate Reviewable Test Cases</h2>
        {selected && <span className="badge badge-tag">{selected.id}</span>}
      </div>

      {selected ? (
        <>
          <div
            style={{
              background: "var(--bg-base)",
              padding: "18px",
              borderRadius: "var(--radius-md)",
              border: "1px solid var(--border-subtle)",
              marginBottom: 20,
            }}
          >
            <h3 style={{ margin: "0 0 8px", fontSize: "1rem", color: "#fff" }}>
              {selected.title}
            </h3>
            <p style={{ margin: "0 0 12px", fontSize: "0.86rem", color: "var(--text-dim)", lineHeight: 1.5 }}>
              {selected.user_story || "No user story text."}
            </p>
            <strong style={{ fontSize: "0.8rem", color: "var(--teal)" }}>
              Acceptance Criteria to automate:
            </strong>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: "0.82rem", color: "#cbd5e1" }}>
              {selected.acceptance_criteria?.map((ac, idx) => (
                <li key={idx}>{ac}</li>
              ))}
            </ul>
          </div>

          <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 24 }}>
            <button className="btn-primary" onClick={onGenerate}>
              ⚡ Generate Positive & Negative Case Drafts
            </button>
            <span style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
              Generates explicit actions, expected results, and synthetic positive/negative test data.
            </span>
          </div>

          {casesForStory.length > 0 && (
            <div>
              <h3 style={{ fontSize: "1rem", color: "#fff", marginBottom: 12 }}>
                Generated Cases for this Story ({casesForStory.length})
              </h3>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Title</th>
                      <th>Type</th>
                      <th>Priority</th>
                      <th>Status</th>
                      <th>Steps Count</th>
                    </tr>
                  </thead>
                  <tbody>
                    {casesForStory.map((tc) => (
                      <tr key={tc.id}>
                        <td>
                          <code>{tc.id}</code>
                        </td>
                        <td style={{ fontWeight: 600 }}>{tc.title}</td>
                        <td>
                          <span className="badge badge-tag">{tc.test_type}</span>
                        </td>
                        <td>{tc.priority}</td>
                        <td>
                          <span
                            className={`badge ${
                              tc.status === "Approved"
                                ? "badge-approved"
                                : tc.status === "Rejected"
                                ? "badge-rejected"
                                : "badge-draft"
                            }`}
                          >
                            {tc.status}
                          </span>
                        </td>
                        <td>{tc.steps?.length ?? 0} steps</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      ) : (
        <p style={{ color: "var(--text-muted)", fontSize: "0.84rem" }}>
          Select an active story in the top bar to generate positive and negative case drafts.
        </p>
      )}
    </div>
  );
}

// ==========================================
// 04 / TEST CASES (HUMAN REVIEW & EDITING)
// ==========================================
function TestCasesView({
  cases,
  requirements,
  selectedStoryId,
  onUpdate,
  onDelete,
  onRegenerate,
}: {
  cases: TestCase[];
  requirements: Requirement[];
  selectedStoryId: string;
  onUpdate: (item: TestCase) => void;
  onDelete: (id: string) => void;
  onRegenerate: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("All");
  const [priorityFilter, setPriorityFilter] = useState("All");
  const [typeFilter, setTypeFilter] = useState("All");
  const [activeCaseId, setActiveCaseId] = useState("");
  const [reviewResult, setReviewResult] = useState<{ passed: boolean; issues: string[] } | null>(null);
  const [reviewing, setReviewing] = useState(false);

  const priorities = ["All", ...Array.from(new Set(cases.map((c) => c.priority || "Medium")))];
  const testTypes = ["All", ...Array.from(new Set(cases.map((c) => c.test_type || "Functional")))];

  const filtered = cases.filter((c) => {
    const textMatch = !query || `${c.id} ${c.title}`.toLowerCase().includes(query.toLowerCase());
    const statusMatch = statusFilter === "All" || c.status === statusFilter;
    const priorityMatch = priorityFilter === "All" || c.priority === priorityFilter;
    const typeMatch = typeFilter === "All" || c.test_type === typeFilter;
    return textMatch && statusMatch && priorityMatch && typeMatch;
  });

  const activeCase = filtered.find((c) => c.id === activeCaseId) ?? filtered[0];

  // Run automated review check when active case changes
  useEffect(() => {
    if (activeCase) {
      setReviewing(true);
      api<{ passed: boolean; issues: string[] }>(`/api/cases/${activeCase.id}/review`)
        .then((res) => setReviewResult(res))
        .catch(() => setReviewResult(null))
        .finally(() => setReviewing(false));
    } else {
      setReviewResult(null);
    }
  }, [activeCase?.id]);

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Human Review & Case Traceability</h2>
        <span className="badge badge-tag">{filtered.length} filtered cases</span>
      </div>

      {/* Filter toolbar */}
      <div className="filter-bar">
        <input
          type="text"
          placeholder="Search by ID or Title..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="All">All Statuses</option>
          <option value="Draft">Draft</option>
          <option value="Approved">Approved</option>
          <option value="Rejected">Rejected</option>
        </select>
        <select value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value)}>
          {priorities.map((p) => (
            <option key={p} value={p}>
              Priority: {p}
            </option>
          ))}
        </select>
        <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          {testTypes.map((t) => (
            <option key={t} value={t}>
              Type: {t}
            </option>
          ))}
        </select>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <ExportCaseButton format="json" reqId={selectedStoryId} status={statusFilter} />
          <ExportCaseButton format="csv" reqId={selectedStoryId} status={statusFilter} />
          <ExportCaseButton format="xlsx" reqId={selectedStoryId} status={statusFilter} />
          <ExportCaseButton format="markdown" reqId={selectedStoryId} status={statusFilter} />
        </div>
      </div>

      <div className="grid-2">
        {/* Cases List */}
        <div style={{ maxHeight: "720px", overflowY: "auto" }}>
          {filtered.map((item) => (
            <div
              key={item.id}
              className={`case-item ${activeCase?.id === item.id ? "selected" : ""}`}
              onClick={() => setActiveCaseId(item.id)}
            >
              <span
                className={`badge ${
                  item.status === "Approved"
                    ? "badge-approved"
                    : item.status === "Rejected"
                    ? "badge-rejected"
                    : "badge-draft"
                }`}
              >
                {item.status}
              </span>
              <div className="case-title">
                <strong>{item.title}</strong>
                <small>
                  <code>{item.id}</code> · {item.test_type} · {item.priority} ·{" "}
                  {item.steps?.length ?? 0} steps
                </small>
              </div>
            </div>
          ))}
          {!filtered.length && (
            <p style={{ color: "var(--text-muted)", fontSize: "0.84rem" }}>
              No cases match these filters.
            </p>
          )}
        </div>

        {/* Detailed Editor */}
        {activeCase ? (
          <CaseEditor
            key={activeCase.id}
            caseItem={activeCase}
            reviewResult={reviewResult}
            reviewing={reviewing}
            onUpdate={onUpdate}
            onDelete={() => onDelete(activeCase.id)}
            onRegenerate={() => onRegenerate(activeCase.id)}
          />
        ) : (
          <p style={{ color: "var(--text-muted)", fontSize: "0.84rem" }}>
            Select a test case to edit steps or approve.
          </p>
        )}
      </div>
    </div>
  );
}

function CaseEditor({
  caseItem,
  reviewResult,
  reviewing,
  onUpdate,
  onDelete,
  onRegenerate,
}: {
  caseItem: TestCase;
  reviewResult: { passed: boolean; issues: string[] } | null;
  reviewing: boolean;
  onUpdate: (item: TestCase) => void;
  onDelete: () => void;
  onRegenerate: () => void;
}) {
  const [draft, setDraft] = useState<TestCase>(caseItem);

  function patchStep(index: number, key: keyof Step, val: string) {
    setDraft((curr) => ({
      ...curr,
      steps: curr.steps.map((st, i) => (i === index ? { ...st, [key]: val } : st)),
    }));
  }

  return (
    <div className="editor-panel">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <h3 style={{ margin: 0, fontSize: "1.1rem", color: "#fff" }}>
          Edit {draft.id}
        </h3>
        <span
          className={`badge ${
            draft.status === "Approved"
              ? "badge-approved"
              : draft.status === "Rejected"
              ? "badge-rejected"
              : "badge-draft"
          }`}
        >
          {draft.status}
        </span>
      </div>

      {/* Automated Traceability Check Results */}
      <div style={{ marginBottom: 16 }}>
        {reviewing ? (
          <div style={{ fontSize: "0.76rem", color: "var(--teal)" }}>
            Checking criteria traceability...
          </div>
        ) : reviewResult ? (
          reviewResult.passed ? (
            <div className="banner success" style={{ padding: "8px 12px", margin: 0, fontSize: "0.78rem" }}>
              ✓ Criterion traceability and basic structure passed. Human approval is still required.
            </div>
          ) : (
            <div className="banner error" style={{ padding: "8px 12px", margin: 0, fontSize: "0.78rem" }}>
              ⚠️ Review findings: {reviewResult.issues.join(" · ")}
            </div>
          )
        ) : null}
      </div>

      <div className="form-group">
        <label>Title</label>
        <input
          type="text"
          value={draft.title}
          onChange={(e) => setDraft({ ...draft, title: e.target.value })}
        />
      </div>

      <div className="grid-3" style={{ marginBottom: 14 }}>
        <div className="form-group">
          <label>Test Type</label>
          <input
            type="text"
            value={draft.test_type}
            onChange={(e) => setDraft({ ...draft, test_type: e.target.value })}
          />
        </div>
        <div className="form-group">
          <label>Priority</label>
          <select
            value={draft.priority}
            onChange={(e) => setDraft({ ...draft, priority: e.target.value })}
          >
            <option value="High">High</option>
            <option value="Medium">Medium</option>
            <option value="Low">Low</option>
          </select>
        </div>
        <div className="form-group">
          <label>Review Status</label>
          <select
            value={draft.status}
            onChange={(e) => setDraft({ ...draft, status: e.target.value })}
          >
            <option value="Draft">Draft</option>
            <option value="Approved">Approved</option>
            <option value="Rejected">Rejected</option>
          </select>
        </div>
      </div>

      {/* Steps Editor */}
      <div style={{ maxHeight: "360px", overflowY: "auto", marginBottom: 16 }}>
        {draft.steps?.map((step, idx) => (
          <div key={idx} className="step-card">
            <div className="step-header">Step {idx + 1}</div>
            <div className="form-group" style={{ marginBottom: 8 }}>
              <label>Action (e.g. Fill Username input, Click Submit button)</label>
              <input
                type="text"
                value={step.action}
                onChange={(e) => patchStep(idx, "action", e.target.value)}
              />
            </div>
            <div className="grid-2" style={{ marginBottom: 8 }}>
              <div className="form-group" style={{ margin: 0 }}>
                <label>Test Data</label>
                <input
                  type="text"
                  value={step.test_data ?? ""}
                  onChange={(e) => patchStep(idx, "test_data", e.target.value)}
                />
              </div>
              <div className="form-group" style={{ margin: 0 }}>
                <label>Locator Requirement</label>
                <input
                  type="text"
                  value={step.locator_requirement ?? ""}
                  onChange={(e) => patchStep(idx, "locator_requirement", e.target.value)}
                />
              </div>
            </div>
            <div className="form-group" style={{ margin: 0 }}>
              <label>Expected Result</label>
              <textarea
                style={{ minHeight: "48px" }}
                value={step.expected_result ?? step.expected ?? ""}
                onChange={(e) => patchStep(idx, "expected_result", e.target.value)}
              />
            </div>
          </div>
        ))}
      </div>

      {/* Action Buttons */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
        <button className="btn-primary" onClick={() => onUpdate(draft)}>
          Save Edits
        </button>
        <button
          className="btn-approve"
          onClick={() => onUpdate({ ...draft, status: "Approved" })}
        >
          ✓ Approve
        </button>
        <button
          className="btn-reject"
          onClick={() => onUpdate({ ...draft, status: "Rejected" })}
        >
          ✕ Reject
        </button>
        <button className="btn-secondary" onClick={onRegenerate}>
          ↺ Regenerate Scenario
        </button>
        <button className="btn-danger" style={{ marginLeft: "auto" }} onClick={onDelete}>
          Delete
        </button>
      </div>
    </div>
  );
}

function ExportCaseButton({
  format,
  reqId,
  status,
}: {
  format: string;
  reqId?: string;
  status?: string;
}) {
  async function download() {
    try {
      const q = new URLSearchParams({ format });
      if (reqId) q.set("requirement_id", reqId);
      if (status && status !== "All") q.set("status_filter", status);
      const res = await fetch(`${API_BASE}/api/export/cases?${q}`);
      if (!res.ok) throw new Error("Failed to export cases");
      const blob = await res.blob();
      const ext = format === "markdown" ? "md" : format === "xlsx" ? "xlsx" : format;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `test-cases.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      window.alert("Could not download export.");
    }
  }

  return (
    <button className="btn-secondary" style={{ padding: "6px 12px", fontSize: "0.74rem" }} onClick={download}>
      {format.toUpperCase()}
    </button>
  );
}

// ==========================================
// 05 / FIND ELEMENTS (LOCATORS DISCOVERY)
// ==========================================
function ElementsView({
  selected,
  settings,
  credentials,
  onCredentialsChange,
  onSaveTarget,
  onDiscover,
}: {
  selected: Requirement | null;
  settings: SettingsView | null;
  credentials: RuntimeCredentials;
  onCredentialsChange: (creds: RuntimeCredentials) => void;
  onSaveTarget: (target: Target) => void;
  onDiscover: (target: Target, creds?: RuntimeCredentials) => void;
}) {
  const [target, setTarget] = useState<Target>(emptyTarget());

  useEffect(() => {
    setTarget(selected?.target ? { ...emptyTarget(), ...selected.target } : emptyTarget());
  }, [selected?.id, selected?.target]);

  function update(key: keyof Target, val: string | boolean) {
    setTarget((curr) => ({ ...curr, [key]: val }));
  }

  const authRequired = target.authentication_type === "Username & Password";
  const canDiscover =
    selected &&
    target.application_url &&
    (!authRequired || (credentials.username && credentials.password));

  return (
    <div className="grid-2">
      {/* Target Setup */}
      <div className="panel">
        <div className="panel-header">
          <h2>Story Target & Guidance</h2>
          {selected && <span className="badge badge-tag">{selected.id}</span>}
        </div>

        <div className="form-group">
          <label>Application Website URL</label>
          <input
            type="text"
            placeholder="https://qa.example.com"
            value={target.application_url}
            onChange={(e) => update("application_url", e.target.value)}
          />
        </div>

        <div className="grid-3">
          <div className="form-group">
            <label>Authentication</label>
            <select
              value={target.authentication_type}
              onChange={(e) => update("authentication_type", e.target.value)}
            >
              <option value="No Authentication">No Authentication</option>
              <option value="Username & Password">Username & Password</option>
              <option value="SSO">SSO</option>
            </select>
          </div>
          <div className="form-group">
            <label>Browser</label>
            <select
              value={target.browser}
              onChange={(e) => update("browser", e.target.value)}
            >
              <option value="chromium">Chromium</option>
              <option value="firefox">Firefox</option>
              <option value="webkit">WebKit (Safari)</option>
            </select>
          </div>
          <div className="form-group">
            <label>Execution Mode</label>
            <select
              value={target.headless ? "headless" : "headed"}
              onChange={(e) => update("headless", e.target.value === "headless")}
            >
              <option value="headless">Headless</option>
              <option value="headed">Headed (Visual)</option>
            </select>
          </div>
        </div>

        {authRequired && (
          <div
            style={{
              background: "var(--bg-base)",
              padding: 14,
              borderRadius: "var(--radius-md)",
              borderLeft: "3px solid var(--teal)",
              marginBottom: 16,
            }}
          >
            <strong style={{ fontSize: "0.8rem", color: "#fff", display: "block", marginBottom: 8 }}>
              Session Sign-In Credentials (Kept in memory, never stored in DB)
            </strong>
            <div className="grid-2" style={{ marginBottom: 10 }}>
              <div className="form-group" style={{ margin: 0 }}>
                <label>Username</label>
                <input
                  type="text"
                  value={credentials.username}
                  onChange={(e) =>
                    onCredentialsChange({ ...credentials, username: e.target.value })
                  }
                  autoComplete="username"
                />
              </div>
              <div className="form-group" style={{ margin: 0 }}>
                <label>Password</label>
                <input
                  type="password"
                  value={credentials.password}
                  onChange={(e) =>
                    onCredentialsChange({ ...credentials, password: e.target.value })
                  }
                  autoComplete="current-password"
                />
              </div>
            </div>
            <div className="grid-3">
              <div className="form-group" style={{ margin: 0 }}>
                <label>Username Label (opt)</label>
                <input
                  type="text"
                  value={target.username_label}
                  onChange={(e) => update("username_label", e.target.value)}
                />
              </div>
              <div className="form-group" style={{ margin: 0 }}>
                <label>Password Label (opt)</label>
                <input
                  type="text"
                  value={target.password_label}
                  onChange={(e) => update("password_label", e.target.value)}
                />
              </div>
              <div className="form-group" style={{ margin: 0 }}>
                <label>Submit Button Label (opt)</label>
                <input
                  type="text"
                  value={target.submit_label}
                  onChange={(e) => update("submit_label", e.target.value)}
                />
              </div>
            </div>
          </div>
        )}

        <div className="form-group">
          <label>Discovery Guidance (Optional)</label>
          <textarea
            placeholder="For example: focus on login form, header navigation, and project create buttons."
            value={target.guidance}
            onChange={(e) => update("guidance", e.target.value)}
          />
        </div>

        <div style={{ display: "flex", gap: 12 }}>
          <button
            className="btn-secondary"
            disabled={!selected || !target.application_url}
            onClick={() => onSaveTarget(target)}
          >
            Save Target Configuration
          </button>
          <button
            className="btn-primary"
            disabled={!canDiscover}
            onClick={() => onDiscover(target, authRequired ? credentials : undefined)}
          >
            🔍 Find Elements Across All Story Cases
          </button>
        </div>
      </div>

      {/* Discovered Locators Table */}
      <div className="panel">
        <div className="panel-header">
          <h2>Shared Locator Repository</h2>
          <span className="badge badge-tag">
            {selected?.locators?.length ?? 0} saved elements
          </span>
        </div>

        {selected?.locators?.length ? (
          <div style={{ maxHeight: "640px", overflowY: "auto" }}>
            {selected.locators.map((loc, idx) => (
              <div
                key={loc.id ?? idx}
                style={{
                  background: "var(--bg-base)",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "var(--radius-md)",
                  padding: 14,
                  marginBottom: 10,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <strong style={{ color: "#fff", fontSize: "0.88rem" }}>
                    {loc.element}
                  </strong>
                  <span className={`badge ${loc.validated ? "badge-pass" : "badge-blocked"}`}>
                    {loc.validated ? "VALIDATED" : "UNVERIFIED"}
                  </span>
                </div>
                <div style={{ fontSize: "0.76rem", color: "var(--text-dim)", marginBottom: 4 }}>
                  Tag: <code>{loc.tag}</code> · XPath: <code>{loc.xpath}</code>
                </div>
                <div style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
                  Alternatives: {loc.candidates?.filter((c) => c.valid).length ?? 0} valid /{" "}
                  {loc.candidates?.length ?? 0} candidates · Confidence:{" "}
                  {Math.round((loc.confidence ?? 1) * 100)}%
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p style={{ color: "var(--text-muted)", fontSize: "0.84rem" }}>
            Configure the target website above and run element discovery to inspect the DOM.
          </p>
        )}
      </div>
    </div>
  );
}

// ==========================================
// 06 / SCRIPT GENERATION VIEW
// ==========================================
function ScriptsView({
  cases,
  selected,
  run,
  onMessage,
}: {
  cases: TestCase[];
  selected: Requirement | null;
  run: (label: string, op: () => Promise<void>) => Promise<void>;
  onMessage: (msg: string) => void;
}) {
  const [activeCaseId, setActiveCaseId] = useState("");
  const [source, setSource] = useState("");
  const [copied, setCopied] = useState(false);

  const activeCase = cases.find((c) => c.id === activeCaseId) ?? cases[0];

  useEffect(() => {
    if (activeCase) {
      setActiveCaseId(activeCase.id);
      api<{ source: string }>(`/api/cases/${activeCase.id}/script`)
        .then((res) => setSource(res.source || ""))
        .catch(() => setSource(""));
    } else {
      setSource("");
    }
  }, [activeCase?.id]);

  async function generate() {
    if (!activeCase) return;
    await run(`Generating Playwright Python script for ${activeCase.id}...`, async () => {
      const res = await api<{ source: string }>(`/api/cases/${activeCase.id}/script`, {
        method: "POST",
        body: JSON.stringify({ case_id: activeCase.id }),
      });
      setSource(res.source);
      onMessage(`Generated script for ${activeCase.id}. Review and save it before standalone execution.`);
    });
  }

  async function save() {
    if (!activeCase || !source.trim()) return;
    await run("Validating syntax and saving script...", async () => {
      await api(`/api/cases/${activeCase.id}/script`, {
        method: "PUT",
        body: JSON.stringify({ source }),
      });
      onMessage(`Script saved to version history and filesystem.`);
    });
  }

  function download() {
    if (!activeCase || !source) return;
    const blob = new Blob([source], { type: "text/x-python" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${activeCase.id}.py`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function copyScript() {
    if (!source) return;
    try {
      await navigator.clipboard.writeText(source);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      window.alert("Clipboard write failed.");
    }
  }

  const hasTodos = source.includes("TODO:");

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Generate and Edit Playwright Scripts</h2>
        <span className="badge badge-tag">{selected?.id || "No story selected"}</span>
      </div>

      <div style={{ display: "flex", gap: 14, alignItems: "center", marginBottom: 16 }}>
        <select
          value={activeCase?.id ?? ""}
          onChange={(e) => setActiveCaseId(e.target.value)}
          style={{ minWidth: 260 }}
        >
          <option value="">Select test case</option>
          {cases.map((c) => (
            <option key={c.id} value={c.id}>
              {c.id} · {c.title}
            </option>
          ))}
        </select>
        <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
          Target: {selected?.target?.application_url || "Target not configured yet"}
        </span>
      </div>

      {hasTodos && (
        <div className="banner error" style={{ marginBottom: 12 }}>
          ⚠️ This script contains unmapped steps (TODO). Review actions and map locators before standalone use.
        </div>
      )}

      <textarea
        className="code-box"
        spellCheck={false}
        value={source}
        onChange={(e) => setSource(e.target.value)}
        placeholder="Generate a standalone Playwright script for an approved test case..."
      />

      <div style={{ display: "flex", gap: 12, marginTop: 14 }}>
        <button className="btn-primary" onClick={generate} disabled={!activeCase}>
          ⚡ Generate Script
        </button>
        <button className="btn-secondary" onClick={save} disabled={!activeCase || !source.trim()}>
          Validate & Save Script
        </button>
        <button className="btn-secondary" onClick={copyScript} disabled={!source.trim()}>
          {copied ? "✓ Copied!" : "📋 Copy to Clipboard"}
        </button>
        <button className="btn-secondary" onClick={download} disabled={!source.trim()}>
          ⬇ Download .py
        </button>
      </div>
    </div>
  );
}

// ==========================================
// 07 / TEST EXECUTION VIEW
// ==========================================
function ExecutionView({
  cases,
  selected,
  settings,
  credentials,
  onCredentialsChange,
  onExecuteBatch,
  onPreviewImage,
}: {
  cases: TestCase[];
  selected: Requirement | null;
  settings: SettingsView | null;
  credentials: RuntimeCredentials;
  onCredentialsChange: (creds: RuntimeCredentials) => void;
  onExecuteBatch: (caseIds: string[], creds?: RuntimeCredentials) => Promise<void>;
  onPreviewImage: (src: string) => void;
}) {
  const approved = cases.filter((c) => c.status === "Approved");
  const [selectedCaseIds, setSelectedCaseIds] = useState<string[]>([]);
  const [lastOutcomes, setLastOutcomes] = useState<Step[]>([]);
  const authRequired = selected?.target?.authentication_type === "Username & Password";

  function toggleCase(id: string) {
    setSelectedCaseIds((curr) =>
      curr.includes(id) ? curr.filter((x) => x !== id) : [...curr, id]
    );
  }

  function selectAll() {
    setSelectedCaseIds(approved.map((c) => c.id));
  }

  function clearAll() {
    setSelectedCaseIds([]);
  }

  const executionDisabled = !settings?.execution_enabled;

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Execute Approved Test Cases in Isolated Browser</h2>
        <span className="badge badge-approved">{approved.length} approved cases</span>
      </div>

      {executionDisabled && (
        <div className="banner error" style={{ marginBottom: 16 }}>
          ⚠️ Browser execution requires a worker environment with Playwright installed. If running serverless on Vercel, attach a dedicated browser service.
        </div>
      )}

      {authRequired && (
        <div
          style={{
            background: "var(--bg-base)",
            padding: 14,
            borderRadius: "var(--radius-md)",
            borderLeft: "3px solid var(--teal)",
            marginBottom: 16,
          }}
        >
          <strong style={{ fontSize: "0.8rem", color: "#fff", display: "block", marginBottom: 6 }}>
            Session Sign-in Details
          </strong>
          <div className="grid-2">
            <input
              type="text"
              placeholder="Username"
              value={credentials.username}
              onChange={(e) =>
                onCredentialsChange({ ...credentials, username: e.target.value })
              }
            />
            <input
              type="password"
              placeholder="Password"
              value={credentials.password}
              onChange={(e) =>
                onCredentialsChange({ ...credentials, password: e.target.value })
              }
            />
          </div>
        </div>
      )}

      {/* Case Checkboxes */}
      <div style={{ marginBottom: 18 }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 10 }}>
          <button className="btn-secondary" style={{ padding: "6px 12px", fontSize: "0.76rem" }} onClick={selectAll}>
            Select All Approved
          </button>
          <button className="btn-secondary" style={{ padding: "6px 12px", fontSize: "0.76rem" }} onClick={clearAll}>
            Clear Selection
          </button>
          <span style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
            {selectedCaseIds.length} of {approved.length} cases chosen
          </span>
        </div>

        <div style={{ maxHeight: "280px", overflowY: "auto" }}>
          {approved.map((tc) => (
            <label
              key={tc.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "10px 14px",
                background: "var(--bg-base)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-subtle)",
                marginBottom: 6,
                cursor: "pointer",
              }}
            >
              <input
                type="checkbox"
                checked={selectedCaseIds.includes(tc.id)}
                onChange={() => toggleCase(tc.id)}
              />
              <span style={{ fontWeight: 600, fontSize: "0.85rem", color: "#fff" }}>
                {tc.title}
              </span>
              <small style={{ color: "var(--text-muted)", marginLeft: "auto" }}>
                <code>{tc.id}</code> · {tc.steps?.length ?? 0} steps
              </small>
            </label>
          ))}
          {!approved.length && (
            <p style={{ color: "var(--text-muted)", fontSize: "0.84rem" }}>
              No approved test cases. Approve cases in the Test cases tab before execution.
            </p>
          )}
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 24 }}>
        <button
          className="btn-primary"
          disabled={!selectedCaseIds.length || executionDisabled}
          onClick={() =>
            onExecuteBatch(selectedCaseIds, authRequired ? credentials : undefined)
          }
        >
          ▶ Execute Selected ({selectedCaseIds.length})
        </button>
        <button
          className="btn-secondary"
          disabled={!approved.length || executionDisabled}
          onClick={() =>
            onExecuteBatch(
              approved.map((c) => c.id),
              authRequired ? credentials : undefined
            )
          }
        >
          ▶ Execute All Approved ({approved.length})
        </button>
      </div>

      <p style={{ color: "var(--text-muted)", fontSize: "0.78rem", lineHeight: 1.5 }}>
        Each case executes in an isolated browser context. Outcomes and visual screenshot evidence
        are permanently recorded in SQLite. Batch runs continue even if an individual test fails.
      </p>
    </div>
  );
}

// ==========================================
// 08 / EXECUTION HISTORY VIEW
// ==========================================
function HistoryView({
  runs,
  onPreviewImage,
}: {
  runs: Run[];
  onPreviewImage: (src: string) => void;
}) {
  const [selectedRunId, setSelectedRunId] = useState("");
  const [detail, setDetail] = useState<{
    run: Run;
    results: TestResult[];
  } | null>(null);

  useEffect(() => {
    const chosen = runs.find((r) => r.id === selectedRunId) ?? runs[0];
    if (chosen) {
      setSelectedRunId(chosen.id);
      api<typeof detail>(`/api/runs/${chosen.id}`)
        .then(setDetail)
        .catch(() => setDetail(null));
    } else {
      setDetail(null);
    }
  }, [selectedRunId, runs.length]);

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Execution Run History & Visual Evidence</h2>
        {detail && <span className="badge badge-tag">{detail.run.id}</span>}
      </div>

      <div style={{ display: "flex", gap: 14, alignItems: "center", marginBottom: 20 }}>
        <select
          value={selectedRunId}
          onChange={(e) => setSelectedRunId(e.target.value)}
          style={{ minWidth: 320 }}
        >
          {runs.map((r) => (
            <option key={r.id} value={r.id}>
              {r.id} · {new Date(r.started_at).toLocaleString()} · {r.status}
            </option>
          ))}
        </select>
        {detail && (
          <a
            href={`${API_BASE}/api/export/evidence/${detail.run.id}`}
            download
            className="btn-secondary"
            style={{ textDecoration: "none" }}
          >
            📦 Download Run Evidence ZIP
          </a>
        )}
      </div>

      {detail ? (
        <>
          <div className="metrics-row" style={{ marginBottom: 20 }}>
            {Object.entries(detail.run.summary || {}).map(([k, v]) => (
              <div key={k} className="metric-card" style={{ padding: 14 }}>
                <span>{k}</span>
                <strong style={{ fontSize: "1.5rem", margin: "4px 0" }}>{v}</strong>
                <small>Run outcome</small>
              </div>
            ))}
          </div>

          <div>
            {detail.results.map((res, i) => (
              <div
                key={res.id ?? i}
                style={{
                  background: "var(--bg-base)",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "var(--radius-lg)",
                  padding: 18,
                  marginBottom: 16,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <h3 style={{ margin: 0, fontSize: "1rem", color: "#fff" }}>
                    {res.title || res.test_case_id}
                  </h3>
                  <span
                    className={`badge ${
                      res.status === "PASS"
                        ? "badge-pass"
                        : res.status === "FAIL"
                        ? "badge-fail"
                        : "badge-blocked"
                    }`}
                  >
                    {res.status} · {res.duration?.toFixed(2)}s
                  </span>
                </div>

                {res.error && (
                  <div className="banner error" style={{ padding: "8px 12px", margin: "8px 0" }}>
                    {res.error}
                  </div>
                )}

                {/* Steps Table */}
                {res.steps && res.steps.length > 0 && (
                  <div className="table-wrap" style={{ marginTop: 12 }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Step #</th>
                          <th>Action</th>
                          <th>Expected</th>
                          <th>Actual</th>
                          <th>Status</th>
                          <th>Duration</th>
                          <th>Evidence</th>
                        </tr>
                      </thead>
                      <tbody>
                        {res.steps.map((st, sidx) => {
                          const screenshotName = st.screenshot_path
                            ? st.screenshot_path.split(/[\\/]/).pop()
                            : "";
                          const screenshotUrl = screenshotName
                            ? `${API_BASE}/api/evidence/${detail.run.id}/${res.test_case_id}/${screenshotName}`
                            : "";

                          return (
                            <tr key={sidx}>
                              <td>{st.step_number || sidx + 1}</td>
                              <td>{st.action}</td>
                              <td>{st.expected || "—"}</td>
                              <td>{st.actual || "—"}</td>
                              <td>
                                <span
                                  className={`badge ${
                                    st.status === "PASS"
                                      ? "badge-pass"
                                      : st.status === "FAIL"
                                      ? "badge-fail"
                                      : "badge-blocked"
                                  }`}
                                >
                                  {st.status}
                                </span>
                              </td>
                              <td>{st.duration ? `${st.duration.toFixed(2)}s` : "—"}</td>
                              <td>
                                {screenshotUrl ? (
                                  <button
                                    className="btn-secondary"
                                    style={{ padding: "4px 8px", fontSize: "0.72rem" }}
                                    onClick={() => onPreviewImage(screenshotUrl)}
                                  >
                                    📷 View
                                  </button>
                                ) : (
                                  "—"
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      ) : (
        <p style={{ color: "var(--text-muted)", fontSize: "0.84rem" }}>
          No runs recorded yet. Execute test cases to view historical traces and screenshots.
        </p>
      )}
    </div>
  );
}

// ==========================================
// 09 / REPORTING VIEW
// ==========================================
function ReportingView({
  report,
  runs,
}: {
  report: Report | null;
  runs: Run[];
}) {
  const [runFilter, setRunFilter] = useState("All runs");
  const [priorityFilter, setPriorityFilter] = useState("All priorities");
  const [statusFilter, setStatusFilter] = useState("All statuses");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");

  const rows = report?.results ?? [];

  const filtered = rows.filter((r) => {
    const runMatch = runFilter === "All runs" || r.run_id === runFilter;
    const priorityMatch = priorityFilter === "All priorities" || r.priority === priorityFilter;
    const statusMatch = statusFilter === "All statuses" || r.status === statusFilter;
    const d = r.run_started_at ? r.run_started_at.slice(0, 10) : "";
    const fromMatch = !fromDate || d >= fromDate;
    const toMatch = !toDate || d <= toDate;
    return runMatch && priorityMatch && statusMatch && fromMatch && toMatch;
  });

  const counts: Record<string, number> = {};
  filtered.forEach((r) => {
    counts[r.status] = (counts[r.status] ?? 0) + 1;
  });

  const pass = counts.PASS ?? 0;
  const fail = counts.FAIL ?? 0;
  const blocked = counts.BLOCKED ?? 0;
  const executed = pass + fail;
  const passRate = executed ? `${Math.round((pass / executed) * 100)}%` : "—";

  function downloadReport(format: "json" | "csv") {
    let content = "";
    if (format === "json") {
      content = JSON.stringify(filtered, null, 2);
    } else {
      const headers = ["run_id", "test_case_id", "title", "status", "priority", "test_type", "duration"];
      content = [
        headers.join(","),
        ...filtered.map((r) =>
          headers.map((h) => `"${String((r as Record<string, unknown>)[h] ?? "").replaceAll('"', '""')}"`).join(",")
        ),
      ].join("\n");
    }
    const blob = new Blob([content], { type: format === "json" ? "application/json" : "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `execution-report.${format}`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Consolidated Outcomes & Analytics</h2>
        <span className="badge badge-tag">{filtered.length} filtered results</span>
      </div>

      {/* Filter toolbar */}
      <div className="filter-bar">
        <select value={runFilter} onChange={(e) => setRunFilter(e.target.value)}>
          <option value="All runs">All Runs</option>
          {runs.map((r) => (
            <option key={r.id} value={r.id}>
              {r.id}
            </option>
          ))}
        </select>
        <select value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value)}>
          <option value="All priorities">All Priorities</option>
          <option value="High">High</option>
          <option value="Medium">Medium</option>
          <option value="Low">Low</option>
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="All statuses">All Statuses</option>
          <option value="PASS">PASS</option>
          <option value="FAIL">FAIL</option>
          <option value="BLOCKED">BLOCKED</option>
        </select>
        <input
          type="date"
          title="From date"
          value={fromDate}
          onChange={(e) => setFromDate(e.target.value)}
        />
        <input
          type="date"
          title="To date"
          value={toDate}
          onChange={(e) => setToDate(e.target.value)}
        />
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <button className="btn-secondary" onClick={() => downloadReport("json")}>
            JSON
          </button>
          <button className="btn-secondary" onClick={() => downloadReport("csv")}>
            CSV
          </button>
        </div>
      </div>

      <div className="metrics-row">
        <div className="metric-card">
          <span>Total Executed</span>
          <strong>{filtered.length}</strong>
          <small>Filtered results</small>
        </div>
        <div className="metric-card">
          <span>Passed</span>
          <strong style={{ color: "#34d399" }}>{pass}</strong>
          <small>PASSED assertions</small>
        </div>
        <div className="metric-card">
          <span>Failed</span>
          <strong style={{ color: "#fb7185" }}>{fail}</strong>
          <small>FAILED assertions</small>
        </div>
        <div className="metric-card">
          <span>Blocked</span>
          <strong style={{ color: "#fbbf24" }}>{blocked}</strong>
          <small>BLOCKED / unmapped</small>
        </div>
        <div className="metric-card">
          <span>Pass Rate</span>
          <strong style={{ color: "#38bdf8" }}>{passRate}</strong>
          <small>From recorded runs</small>
        </div>
      </div>

      {/* Visual Charts */}
      <div className="charts-grid">
        <div className="chart-card">
          <h3>Status Distribution</h3>
          {["PASS", "FAIL", "BLOCKED"].map((st) => {
            const count = counts[st] ?? 0;
            const max = Math.max(1, ...Object.values(counts));
            const pct = Math.round((count / max) * 100);
            return (
              <div key={st} className="bar-row">
                <span>{st}</span>
                <div className="bar-track">
                  <div
                    className={`bar-fill ${
                      st === "PASS" ? "pass" : st === "FAIL" ? "fail" : "blocked"
                    }`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <strong>{count}</strong>
              </div>
            );
          })}
        </div>

        <div className="chart-card">
          <h3>Outcomes by Priority</h3>
          {["High", "Medium", "Low"].map((prio) => {
            const prioCount = filtered.filter((r) => (r.priority || "Medium") === prio).length;
            const max = Math.max(1, filtered.length);
            const pct = Math.round((prioCount / max) * 100);
            return (
              <div key={prio} className="bar-row">
                <span>{prio}</span>
                <div className="bar-track">
                  <div className="bar-fill general" style={{ width: `${pct}%` }} />
                </div>
                <strong>{prioCount}</strong>
              </div>
            );
          })}
        </div>
      </div>

      {/* Results Table */}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Run ID</th>
              <th>Case ID</th>
              <th>Title</th>
              <th>Status</th>
              <th>Priority</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r, idx) => (
              <tr key={idx}>
                <td>
                  <code>{r.run_id}</code>
                </td>
                <td>
                  <code>{r.test_case_id}</code>
                </td>
                <td style={{ fontWeight: 600 }}>{r.title}</td>
                <td>
                  <span
                    className={`badge ${
                      r.status === "PASS"
                        ? "badge-pass"
                        : r.status === "FAIL"
                        ? "badge-fail"
                        : "badge-blocked"
                    }`}
                  >
                    {r.status}
                  </span>
                </td>
                <td>{r.priority || "Medium"}</td>
                <td>{r.duration?.toFixed(2)}s</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ==========================================
// 10 / SUITES VIEW
// ==========================================
function SuitesView({
  suites,
  cases,
  onSave,
  onDelete,
}: {
  suites: Suite[];
  cases: TestCase[];
  onSave: (suite: { name: string; description: string; case_ids: string[] }) => void;
  onDelete: (id: string) => void;
}) {
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (name.trim()) {
      onSave({ name: name.trim(), description: desc.trim(), case_ids: selectedIds });
      setName("");
      setDesc("");
      setSelectedIds([]);
    }
  }

  return (
    <div className="grid-2">
      <div className="panel">
        <div className="panel-header">
          <h2>Create Test Suite</h2>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Suite Name</label>
            <input
              type="text"
              placeholder="e.g. Smoke Suite, Critical Path"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div className="form-group">
            <label>Description</label>
            <input
              type="text"
              placeholder="Optional suite description"
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
            />
          </div>

          <div className="form-group">
            <label>Select Test Cases to Group ({selectedIds.length} chosen)</label>
            <div style={{ maxHeight: "260px", overflowY: "auto", marginTop: 6 }}>
              {cases.map((c) => (
                <label
                  key={c.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "8px 10px",
                    background: "var(--bg-base)",
                    borderRadius: "var(--radius-md)",
                    marginBottom: 6,
                    fontSize: "0.82rem",
                    color: "#fff",
                    cursor: "pointer",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(c.id)}
                    onChange={(e) =>
                      setSelectedIds(
                        e.target.checked
                          ? [...selectedIds, c.id]
                          : selectedIds.filter((id) => id !== c.id)
                      )
                    }
                  />
                  <span>{c.title}</span>
                  <small style={{ color: "var(--text-muted)", marginLeft: "auto" }}>
                    <code>{c.id}</code>
                  </small>
                </label>
              ))}
            </div>
          </div>

          <button className="btn-primary" style={{ width: "100%", marginTop: 12 }}>
            Create Test Suite
          </button>
        </form>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h2>Configured Suites</h2>
          <span className="badge badge-tag">{suites.length} suites</span>
        </div>

        <div>
          {suites.map((s) => (
            <div
              key={s.id}
              style={{
                background: "var(--bg-base)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--radius-md)",
                padding: 14,
                marginBottom: 12,
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div>
                <strong style={{ color: "#fff", fontSize: "0.95rem" }}>{s.name}</strong>
                <p style={{ margin: "4px 0", fontSize: "0.82rem", color: "var(--text-dim)" }}>
                  {s.description || "No description provided."}
                </p>
                <small style={{ color: "var(--teal)" }}>
                  {s.case_ids?.length ?? s.case_count} test cases linked
                </small>
              </div>
              <button className="btn-danger" onClick={() => onDelete(s.id)}>
                Delete
              </button>
            </div>
          ))}
          {!suites.length && (
            <p style={{ color: "var(--text-muted)", fontSize: "0.84rem" }}>
              No suites created yet. Create suites to organize regression and smoke passes.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ==========================================
// 11 / SETTINGS VIEW
// ==========================================
function SettingsView({
  settings,
  onUpdateSettings,
}: {
  settings: SettingsView | null;
  onUpdateSettings: (newConfig: Partial<SettingsView> & { llm_api_key?: string }) => void;
}) {
  const [provider, setProvider] = useState(settings?.llm_provider || "openai_compatible");
  const [baseUrl, setBaseUrl] = useState(settings?.llm_base_url || "https://api.openai.com/v1");
  const [model, setModel] = useState(settings?.llm_model || "");
  const [apiKey, setApiKey] = useState("");
  const [browser, setBrowser] = useState(settings?.browser || "chromium");
  const [headless, setHeadless] = useState(settings?.headless ?? true);
  const [timeoutMs, setTimeoutMs] = useState(settings?.timeout_ms ?? 10000);

  useEffect(() => {
    if (settings) {
      setProvider(settings.llm_provider || "gemini");
      setBaseUrl(
        settings.llm_base_url ||
          (settings.llm_provider === "gemini"
            ? "https://generativelanguage.googleapis.com/v1beta"
            : settings.llm_provider === "anthropic"
            ? "https://api.anthropic.com/v1"
            : "https://api.openai.com/v1")
      );
      setModel(settings.llm_model || (settings.llm_provider === "gemini" ? "gemini-1.5-flash" : ""));
      setBrowser(settings.browser || "chromium");
      setHeadless(settings.headless ?? true);
      setTimeoutMs(settings.timeout_ms || 10000);
    }
  }, [settings]);

  function handleSave() {
    onUpdateSettings({
      llm_provider: provider,
      llm_base_url: baseUrl,
      llm_model: model,
      llm_api_key: apiKey ? apiKey : undefined,
      browser,
      headless,
      timeout_ms: timeoutMs,
    });
  }

  return (
    <div className="grid-2">
      <div className="panel">
        <div className="panel-header">
          <h2>LLM Provider & Credentials</h2>
        </div>
        <p style={{ color: "var(--text-dim)", fontSize: "0.84rem" }}>
          Configure hosted LLM provider settings (Google Gemini, OpenAI-compatible, or Anthropic Messages). If left
          unconfigured, the system runs in offline draft mode with deterministic heuristics.
        </p>

        <div className="form-group">
          <label>Provider</label>
          <select
            value={provider}
            onChange={(e) => {
              const nextP = e.target.value;
              setProvider(nextP);
              if (nextP === "gemini") {
                setBaseUrl("https://generativelanguage.googleapis.com/v1beta");
                if (!model || model.startsWith("gpt-") || model.startsWith("claude-")) {
                  setModel("gemini-1.5-flash");
                }
              } else if (nextP === "anthropic") {
                setBaseUrl("https://api.anthropic.com/v1");
                if (!model || model.startsWith("gemini-") || model.startsWith("gpt-")) {
                  setModel("claude-3-5-sonnet-20241022");
                }
              } else {
                setBaseUrl("https://api.openai.com/v1");
                if (!model || model.startsWith("gemini-") || model.startsWith("claude-")) {
                  setModel("gpt-4o");
                }
              }
            }}
          >
            <option value="gemini">Google Gemini (Recommended)</option>
            <option value="openai_compatible">OpenAI-Compatible Chat Completions</option>
            <option value="anthropic">Anthropic Messages</option>
          </select>
        </div>

        <div className="form-group">
          <label>API Base URL</label>
          <input
            type="text"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
          />
        </div>

        <div className="form-group">
          <label>Model Name</label>
          <input
            type="text"
            placeholder="e.g. gemini-1.5-flash, gemini-2.0-flash, gemini-2.5-flash, gpt-4o"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
        </div>

        <div className="form-group">
          <label>API Key {settings?.llm_configured && "(Configured)"}</label>
          <input
            type="password"
            placeholder={settings?.llm_configured ? "••••••••••••••••" : "Enter API Key"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>

        <button className="btn-primary" onClick={handleSave}>
          Apply Provider & Runtime Settings
        </button>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h2>Browser & Runtime Settings</h2>
        </div>

        <div className="form-group">
          <label>Default Browser Engine</label>
          <select value={browser} onChange={(e) => setBrowser(e.target.value)}>
            <option value="chromium">Chromium (Chrome, Edge)</option>
            <option value="firefox">Firefox</option>
            <option value="webkit">WebKit (Safari)</option>
          </select>
        </div>

        <div className="form-group">
          <label>Execution Mode</label>
          <select
            value={headless ? "headless" : "headed"}
            onChange={(e) => setHeadless(e.target.value === "headless")}
          >
            <option value="headless">Headless (Background)</option>
            <option value="headed">Headed (Visible Window)</option>
          </select>
        </div>

        <div className="form-group">
          <label>Action Timeout (ms)</label>
          <input
            type="text"
            value={timeoutMs}
            onChange={(e) => setTimeoutMs(Number(e.target.value) || 10000)}
          />
        </div>

        <div
          style={{
            background: "var(--bg-base)",
            padding: 14,
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border-subtle)",
            marginTop: 18,
          }}
        >
          <strong style={{ fontSize: "0.82rem", color: "#fff", display: "block", marginBottom: 6 }}>
            Environment Diagnostic Info
          </strong>
          <div style={{ fontSize: "0.76rem", color: "var(--text-dim)", lineHeight: 1.6 }}>
            <div>Database: <code>{settings?.database_path || "data/automation.db"}</code></div>
            <div>Evidence Dir: <code>{settings?.evidence_dir || "data/evidence"}</code></div>
            <div>Worker Status: {settings?.execution_enabled ? "✓ Ready" : "⚠️ Needs Worker"}</div>
            <div>Storage Persistence: {settings?.storage}</div>
          </div>
        </div>
      </div>
    </div>
  );
}