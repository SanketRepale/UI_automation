# Fieldnotes QA

Fieldnotes QA is a production-oriented, story-centered UI test automation platform. The primary interface is a responsive Next.js application backed by a validated FastAPI API. The original Streamlit workbench remains available for local functional validation and exploratory workflows.

## Architecture

- `web/`: TypeScript/Next.js production UI, deployable to Vercel.
- `api/index.py` and `src/ui_automation/api.py`: FastAPI adapter with validation, CORS allowlisting, optional bearer authentication, request IDs, safe uploads, and structured errors.
- `src/ui_automation/`: reusable requirement agents, locator discovery, Playwright execution, reporting, SQLite repository, and skill loading.
- `app.py`: preserved Streamlit validation interface.
- `skills/`: domain instructions used by the existing agents.

Credentials are accepted only for the active discovery or execution request and are not stored in SQLite, LLM prompts, logs, reports, or generated source. Set `API_AUTH_TOKEN` in any non-local deployment.

## What works

- Upload-only requirement intake from PDF, DOCX, XLSX, CSV, TXT, and Markdown. Analysis extracts stories, acceptance criteria, business rules, scenarios, test data, and missing automation details.
- Skill-loaded requirement analysis, test-case generation, review, locator discovery, script generation, execution, evidence, and reporting agents.
- Step-specific synthetic test data for valid positive inputs and representative invalid or missing negative inputs; users are not prompted to provide scenario data.
- OpenAI-compatible chat-completions and Anthropic Messages provider support; clearly labeled local heuristic drafts when no provider credentials are configured. Username/password values are extracted and redacted locally before any LLM prompt.
- Human review, field-based case editing, approval/rejection, filtering, regeneration, and JSON/CSV/Excel/Markdown export.
- Story-scoped live Playwright inspection that logs in with optional session credentials, ranks elements using optional guidance, and saves validated locator candidates separately for reuse across that story's cases.
- Editable script generation, syntax validation, download, and versioned script persistence.
- Single/bulk execution of approved cases, independent test-case failure handling, per-step PASS/FAIL/BLOCKED records, screenshots, URLs, titles, exceptions, and durable execution history.
- SQLite-backed requirements, per-story target settings, cases, shared locators, scripts, runs, results, and evidence paths; dashboard, history, report charts, and ZIP export. Application credentials are session-only unless explicitly supplied through environment variables.

Generated requirements and tests are proposals for human review. The offline mode does not call an LLM. The execution adapter supports explicit actions (fill, select, check, uncheck, click, and visibility assertions); unsupported or unmapped steps are BLOCKED. Username/password sign-in uses session-only credentials and supplied labels when available, with common visible form controls inferred otherwise. Locator discovery inspects the currently loaded page only. Multi-page state setup, dynamic test-data generation, and AI locator healing require project-specific extensions. Playwright execution uses its Python API directly; the app does not require or claim a separate Playwright MCP server.

## Setup

Use Python 3.11 or newer. From this folder:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
Copy-Item .env.example .env
streamlit run app.py
```

Open the local URL printed by Streamlit. Install `firefox` or `webkit` browsers with `playwright install firefox` or `playwright install webkit` if selected in Find Elements.

Run the production API and UI in separate terminals:

```powershell
uvicorn api.index:app --reload --port 8000
npm install --prefix web
$env:NEXT_PUBLIC_API_BASE_URL="http://localhost:8000"
npm run dev --prefix web
```

The production UI is available at `http://localhost:3000`; API docs are at `http://localhost:8000/api/docs`. Run `streamlit run app.py` independently when validating the original local workbench.

## Vercel deployment

The root `vercel.json` builds the `web/` Next.js app and routes `/api/*` to the FastAPI function. Configure `LLM_API_KEY`, `API_AUTH_TOKEN`, and an exact `CORS_ORIGINS` value in Vercel environment settings; never commit them. Set `EXECUTION_ENABLED=false` on Vercel. Browser discovery and Playwright execution need a worker-capable service with browser binaries, durable storage, and a shared database, so enable those endpoints only in that service.

## LLM configuration

For offline drafts, leave credentials unset. For hosted generation, set these values in `.env`:

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=your-model-name
LLM_API_KEY=your-secret
```

The provider adapter uses the OpenAI-compatible `/chat/completions` endpoint with JSON response mode. Do not commit `.env`. Application `TARGET_USERNAME` and `TARGET_PASSWORD` may be configured there, or entered on Find Elements for the current session. Credentials are excluded from requirement prompts, generated scripts, logs, reports, and SQLite. Standalone scripts read `UI_AUTOMATION_USERNAME` and `UI_AUTOMATION_PASSWORD` from the process environment.

## Workflow

1. Upload requirement documents under **Requirements**; no story or acceptance-criteria text entry is provided.
2. Review the structured analysis and generate drafts under **Test Case Generation**.
3. Search, filter, edit, regenerate, and approve cases under **Test Cases**.
4. Under **Find Elements**, choose a user story, enter its website URL and optional sign-in details/guidance, then discover shared elements for all of that story's cases in one scan.
5. Generate scripts for an individual case using its story's shared validated elements.
6. Run approved cases for a selected story under **Test Execution**. Missing authentication credentials, locators, or unsupported steps report BLOCKED; actual assertion/action failures report FAIL.
7. Inspect runs and masked screenshots under **Execution History** and **Reporting**; download filtered reports or the latest evidence ZIP.

For a step to execute, phrase its action explicitly (for example, “Fill Project Name input”, “Click Create Project button”, or “Verify Project created successfully text”), provide test data when filling, and ensure a matching uniquely validated element exists in the story's shared repository. Keep the expected result precise. Each case begins at its story's target URL in a fresh browser page.

## Data and configuration

- SQLite: `data/automation.db`
- Uploaded files: `data/uploaded_documents/`
- Evidence: `data/evidence/<run-id>/<test-case-id>/`
- Generated source: `data/generated_scripts/`
- Logs: `data/reports/automation.log` (rotating JSON-lines events with UTC timestamp, level, agent/action, run/test/step IDs, locator, status, duration, evidence path, and sanitized error details)
- Runtime settings: environment variables in `.env`; no credentials are hard-coded.

The schema is isolated behind `Database` and `Repository` modules to allow a future PostgreSQL adapter. Skill definitions live under `skills/` and are loaded by their specialized agent classes.

## Tests

```powershell
pytest
```

The unit tests cover offline requirement analysis, test-case drafts, document extraction, and SQLite round trips. Browser-level verification requires an installed Playwright browser and a reachable application target.
