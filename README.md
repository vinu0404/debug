# Financial Document Analyzer

A CrewAI-powered system that analyzes financial documents (PDFs) using four specialized AI agents: **Document Verifier**, **Financial Analyst**, **Risk Assessor**, and **Investment Advisor**.


---

## Architecture

```mermaid
flowchart TD
    subgraph Client
        U[User / API Client]
    end

    subgraph FastAPI["FastAPI Application (main.py)"]
        EP_SYNC["POST /analyze\n(synchronous)"]
        EP_ASYNC["POST /analyze-async\n(queued)"]
        EP_STATUS["GET /analysis/{id}"]
        EP_LIST["GET /analyses"]
        EP_HEALTH["GET /"]
    end

    subgraph Orchestrator["run_crew() — Single PDF Read"]
        PDF_READ["extract_pdf_text()\n(read PDF ONCE)"]
        KICKOFF["crew.kickoff()\npasses {document_text}\nto all agents"]
        PDF_READ --> KICKOFF
    end

    subgraph CrewAI["CrewAI Pipeline (sequential)"]
        A1["1. Verifier Agent\n(has PDF tool as fallback)"]
        A2["2. Financial Analyst\n(uses pre-loaded text)"]
        A3["3. Risk Assessor\n(uses pre-loaded text)"]
        A4["4. Investment Advisor\n(uses pre-loaded text)"]
        A1 --> A2 --> A3 --> A4
    end

    subgraph Tools["Agent Tools (tools.py)"]
        T1["read_financial_document\n(fallback only)"]
        T2["analyze_investment_data\n(extracts $ and % figures)"]
        T3["assess_risk_factors\n(extracts risk paragraphs)"]
        T4["search_tool\n(SerperDevTool)"]
    end

    subgraph Queue["Celery + Redis"]
        CW["Celery Worker\n(celery_worker.py)"]
        RD[(Redis Broker)]
    end

    subgraph Database["PostgreSQL"]
        DB[(analysis_results & users)]
    end

    U -->|upload PDF + query| EP_SYNC
    U -->|upload PDF + query| EP_ASYNC
    U -->|poll status| EP_STATUS
    U -->|list history| EP_LIST

    EP_SYNC --> Orchestrator
    Orchestrator --> CrewAI
    EP_ASYNC -->|dispatch task| RD
    RD --> CW
    CW --> Orchestrator

    A1 -.->|fallback only| T1
    A2 -.-> T4
    A3 -.-> T3
    A4 -.-> T2
    A4 -.-> T4

    EP_SYNC --> DB
    EP_ASYNC --> DB
    CW --> DB
    EP_STATUS --> DB
    EP_LIST --> DB
```

---

## How It Works 

### User Sends a Request

A user sends a **POST** to `/analyze` with a PDF file and a query string:

```
POST http://localhost:8000/analyze
Content-Type: multipart/form-data

file: <tesla_10k.pdf>
query: "What are Tesla's key revenue drivers?"
```

### Request Handling (`analyze_document()` in [main.py](main.py#L111))

| Step | What Happens | Detail |
|------|-------------|--------|
| 1 | **Generate UUID** | `file_id = str(uuid.uuid4())` — unique identifier for this analysis |
| 2 | **Create DB record** | `AnalysisResult(id=file_id, status=PENDING)` is inserted into PostgreSQL |
| 3 | **Read & validate upload** | `await file.read()` — checks file size ≤ 50 MB, rejects with HTTP 413 if too large |
| 4 | **Save PDF to disk** | Written to `data/financial_document_{uuid}.pdf` |
| 5 | **Update status** | DB record set to `PROCESSING`, committed |
| 6 | **Run analysis in thread** | `await asyncio.to_thread(run_crew, query, file_path)` — offloads the blocking CrewAI work to a thread pool so FastAPI's async event loop stays responsive for new query

### `run_crew()` — The Orchestrator ([main.py](main.py#L80))

This run the AI pipeline:

```python
run_crew(query="What are Tesla's key revenue drivers?",
         file_path="data/financial_document_xxx.pdf")
```

**Step 1 — Read PDF once:**
```python
document_text = extract_pdf_text(file_path)
```
The `extract_pdf_text()` function ([tools.py](tools.py#L20)) opens the PDF with PyMuPDF, extracts text from every page, concatenates it.

**Step 2 — Build the Crew:**
```python
financial_crew = Crew(
    agents=[verifier, financial_analyst, risk_assessor, investment_advisor],
    tasks=[verification_task, financial_analysis_task, risk_assessment_task, investment_analysis_task],
    process=Process.sequential,
    verbose=True,
)
```
All 4 agents and 4 tasks are wired into a **sequential pipeline** — each agent runs one after another.

**Step 3 — Kick off:**
```python
result = financial_crew.kickoff(inputs={
    "query": "What are Tesla's key revenue drivers?",
    "file_path": "data/financial_document_uuid...pdf",
    "document_text": "extracted text from pdf",
})
```
CrewAI replaces `{query}`, `{file_path}`, and `{document_text}` placeholders in every agent goal and task description with the actual values. This is how **all 4 agents receive the full PDF text inline** in their prompts — without any agent needing to re-read the file.

### Phase 5 — Sequential Agent Execution

CrewAI runs the 4 tasks **one after another**. Each agent receives the output of all previous agents as additional context.

---

#### Agent 1: Verifier (Document Verification Specialist)

| Detail | Value |
|--------|-------|
| **Role** | Big Four compliance expert |
| **Input** | Task description contains the full `{document_text}` inline |
| **Tools** | `read_financial_document` (fallback only — rarely used) |
| **What it does** | The LLM reads the inline document text, checks for standard financial statement components (income statement, balance sheet, cash-flow statement, notes/disclosures), flags anomalies |
| **Output** | Structured verification report with PASS/FAIL verdict |

The LLM (GPT-4o-mini) sees the full document in its prompt and performs verification purely through reasoning. The `read_financial_document` tool exists as a fallback if the agent decides it needs to re-read the raw PDF file.

---

#### Agent 2: Financial Analyst (Senior Financial Analyst, CFA)

| Detail | Value |
|--------|-------|
| **Input** | `{document_text}` + `{query}` + **output of Agent 1** (verification report) |
| **Tools** | `search_tool` (SerperDevTool — Google search via Serper API) |
| **What it does** | Analyzes the inline text to extract revenue, margins, EPS, cash flow, and other key metrics. May call `search_tool` to get current market context (stock price, industry benchmarks, recent news) |
| **Output** | Detailed financial analysis report with metrics, trends, and data-backed answers to the user's query |

---

#### Agent 3: Risk Assessor (FRM-certified Risk Analyst)

| Detail | Value |
|--------|-------|
| **Input** | `{document_text}` + `{query}` + **outputs of Agents 1 & 2** |
| **Tools** | `assess_risk_factors` |
| **What it does** | The LLM may call `assess_risk_factors(financial_text)` — a regex-based tool that scans for risk keywords across 5 categories, extracts matching paragraphs, and returns them grouped. The LLM then performs qualitative risk analysis on those sections. |
| **Output** | Risk matrix with Low/Medium/High ratings per category |

**How `assess_risk_factors` works internally ([tools.py](tools.py#L163)):**
```
Input text
  → Split into paragraphs
  → For each paragraph, check against 5 keyword lists:
      • Credit & Debt Risk (debt, default, leverage, covenant...)
      • Market & Volatility Risk (volatility, currency, inflation...)
      • Legal & Regulatory Risk (litigation, SEC, compliance...)
      • Operational Risk (restructuring, cybersecurity, supply chain...)
      • Financial Health Concerns (decline, loss, going concern...)
  → Group matching paragraphs by category
  → Return structured extract with indicators
  → LLM reasons over the extract to assign risk ratings
```

---

#### Agent 4: Investment Advisor (FINRA-registered)

| Detail | Value |
|--------|-------|
| **Input** | `{document_text}` + `{query}` + **outputs of Agents 1, 2, & 3** |
| **Tools** | `analyze_investment_data` + `search_tool` |
| **What it does** | The LLM may call `analyze_investment_data(financial_text)` to extract monetary and percentage figures via regex. May also call `search_tool` for macroeconomic context. Synthesizes all prior agent outputs into a final recommendation. |
| **Output** | Professional investment recommendation with thesis, valuation, bull/bear cases, and disclaimers |

**How `analyze_investment_data` works internally ([tools.py](tools.py#L89)):**
```
Input text
  → Regex for monetary values: $X.X million/billion/M/B patterns
  → Regex for percentage values: X.X% patterns
  → Scan paragraphs for metric keywords (revenue, EPS, margin, guidance...)
    that ALSO contain $ or % figures
  → Return structured extraction:
      • All unique monetary figures found
      • All unique percentage figures found
      • Key financial sections with matched keywords
  → LLM uses these real figures to build investment thesis
```

---

### Phase 6 — Result Storage & Response

After `run_crew()` returns, back in `analyze_document()`:

| Step | What Happens |
|------|-------------|
| 1 | **Update DB** — `status=COMPLETED`, `result=<crew output>`, `completed_at=utcnow()` |
| 2 | **Save to file** — `save_analysis_output()` writes the result to `outputs/{filename}_{id}.txt` with a metadata header (analysis ID, source file, query, timestamp) |
| 3 | **Clean up** — Delete the temporary PDF from `data/` |
| 4 | **Return JSON** — Send the response back to the user |

**Success response:**
```json
{
  "status": "success",
  "analysis_id": "a1b2c3d4-...",
  "query": "What are Tesla's key revenue drivers?",
  "analysis": "... comprehensive multi-agent analysis ...",
  "file_processed": "tesla_10k.pdf",
  "output_file": "outputs/tesla_10k_a1b2c3d4.txt"
}
```

**If anything fails:** the `except` block sets `status=FAILED` and `error=<message>` in the DB, then returns HTTP 500.



### Async Path (`/analyze-async`)

The async endpoint lets the user **submit and walk away** — the heavy CrewAI pipeline runs in a separate Celery worker process while the API stays responsive.

#### Step 1 — User Sends Request

```
POST http://localhost:8000/analyze-async
Content-Type: multipart/form-data

file: <tesla_10k.pdf>
query: "Provide a comprehensive investment thesis"
```

#### Step 2 — FastAPI Endpoint (`analyze_document_async()` in [main.py](main.py#L195))

| Step | What Happens | Detail |
|------|-------------|--------|
| 1 | **Generate UUID** | `file_id = str(uuid.uuid4())` |
| 2 | **Read & validate upload** | `await file.read()` — rejects with HTTP 413 if > 50 MB |
| 3 | **Save PDF to disk** | Written to `data/financial_document_{uuid}.pdf` |
| 4 | **Create DB record** | `AnalysisResult(id=file_id, status=PENDING)` inserted into PostgreSQL |
| 5 | **Dispatch to Celery** | `analyze_document_task.delay(file_id, query, file_path)` — serializes the 3 arguments as JSON and pushes a message onto the **Redis** broker queue |
| 6 | **Return immediately** | The user gets the response in milliseconds — no waiting |

**Response (instant):**
```json
{
  "status": "accepted",
  "analysis_id": "a1b2c3d4-...",
  "message": "Analysis queued. Poll GET /analysis/{analysis_id} for results."
}
```

At this point the user's HTTP connection is closed. The actual analysis hasn't started yet — it's sitting as a message in Redis.

#### Step 3 — Redis Broker (Message Queue)

```
Redis Queue: "celery"
  └── Task message: {
        "task": "analyze_document",
        "args": ["a1b2c3d4-...", "Provide a comprehensive investment thesis", "data/financial_document_a1b2c3d4.pdf"],
        "retries": 0
      }
```

Redis holds the task message until a Celery worker picks it up. If no worker is running, the message waits indefinitely in the queue.

#### Step 4 — Celery Worker Picks Up the Task ([celery_worker.py](celery_worker.py#L35))

The worker process (started via `celery -A celery_worker worker --loglevel=info --pool=solo`) constantly polls Redis. When it finds the message:

| Step | What Happens |
|------|-------------|
| 1 | **Fresh imports** — `from database import SessionLocal`, `from agents import ...`, `from task import ...` are imported **inside** the task function (not at module level) to avoid stale state between runs |
| 2 | **New DB session** — `db = SessionLocal()` creates a fresh PostgreSQL session for this task only |
| 3 | **Look up record** — `db.query(AnalysisResult).filter(id == analysis_id).first()` fetches the PENDING record |
| 4 | **Update status** — Sets `status=PROCESSING`, commits to DB |
| 5 | **Read PDF once** — `document_text = extract_pdf_text(file_path)` — same single-read optimization as the sync path |
| 6 | **Build Crew** — Same 4 agents, 4 tasks, `Process.sequential` |
| 7 | **Kick off** — `crew.kickoff(inputs={query, file_path, document_text})` — runs the full sequential pipeline (Verifier → Analyst → Risk Assessor → Advisor) |
| 8 | **Save result to DB** — `status=COMPLETED`, `result=<output>`, `completed_at=utcnow()` |
| 9 | **Save to file** — Writes to `outputs/{filename}_{id}.txt` with metadata header |
| 10 | **Cleanup** — Closes DB session, deletes temporary PDF from `data/` |

**If the task fails:**
- The `except` block sets `status=FAILED` and `error=<message>` in the DB.
- Calls `self.retry(exc=exc, countdown=30 * (retries + 1))` — **auto-retries up to 2 times** with exponential backoff (30s, then 60s).
- The `finally` block always closes the DB session and removes the temp PDF.

#### Step 5 — User Polls for Results

The user checks status by calling:

```
GET http://localhost:8000/analysis/a1b2c3d4-...
```

**While processing:**
```json
{
  "analysis_id": "a1b2c3d4-...",
  "status": "processing",
  "filename": "tesla_10k.pdf",
  "query": "Provide a comprehensive investment thesis",
  "result": null,
  "error": null,
  "created_at": "2026-02-24 10:30:00",
  "completed_at": null
}
```

**When complete:**
```json
{
  "analysis_id": "a1b2c3d4-...",
  "status": "completed",
  "filename": "tesla_10k.pdf",
  "query": "Provide a comprehensive investment thesis",
  "result": "... full multi-agent investment analysis ...",
  "error": null,
  "created_at": "2026-02-24 10:30:00",
  "completed_at": "2026-02-24 10:32:15"
}
```

**If failed (after all retries exhausted):**
```json
{
  "analysis_id": "a1b2c3d4-...",
  "status": "failed",
  "result": null,
  "error": "OpenAI API rate limit exceeded",
  ...
}
```


### Key Design Decisions

| Decision | Why |
|----------|-----|
| **Single PDF read** | `extract_pdf_text()` runs once; text is injected via `{document_text}` into all 4 task descriptions. Without this, each agent would re-read the PDF = 4x I/O + 4x token cost. |
| **`asyncio.to_thread`** | CrewAI's `kickoff()` is blocking (synchronous, can take minutes). Wrapping it in `to_thread` prevents it from freezing FastAPI's async event loop so other requests can still be served. |
| **`Process.sequential`** | Each agent builds on previous outputs — the analyst needs the verifier's PASS, the risk assessor needs the analyst's metrics, and the advisor needs all three reports. |
| **`allow_delegation=False`** | Prevents agents from randomly delegating work to each other, keeping the pipeline flow predictable and debuggable. |
| **Regex tools + LLM reasoning** | Tools like `assess_risk_factors` do lightweight keyword/regex extraction to surface relevant paragraphs; the LLM does the actual qualitative analysis. This gives the agent focused, relevant data instead of processing 80k chars blindly. |

---

## Bugs Found & How They Were Fixed

### Deterministic Bugs (Code-Breaking)

| # | File | Bug | Fix |
|---|------|-----|-----|
| 1 | `agents.py:12` | `llm = llm` — self-referencing undefined variable causing `NameError` | Created a proper `LLM(model="gpt-4o", api_key=...)` instance from crewai |
| 2 | `agents.py:8` | `from crewai.agents import Agent` — wrong import path (`crewai.agents` doesn't exist) | Changed to `from crewai import Agent` |
| 3 | `agents.py:24` | `tool=[...]` — wrong parameter name (singular) | Changed to `tools=[...]` (plural) |
| 4 | `agents.py:24` | `FinancialDocumentTool.read_data_tool` is a raw class method, not a CrewAI tool | Rewrote as standalone `@tool` decorated function |
| 5 | `agents.py:25-27` | `max_iter=1`, `max_rpm=1` — agent can only do 1 iteration, practically useless | Increased to `max_iter=15`, `max_rpm=10` |
| 6 | `agents.py` | `allow_delegation=True` on agents in a single-agent crew causes delegation loops | Set `allow_delegation=False` for all agents (they work in sequence) |
| 7 | `tools.py:6` | `from crewai_tools import tools` — lowercase `tools` doesn't exist as an export | Removed; imported `SerperDevTool` directly from `crewai_tools` |
| 8 | `tools.py:26` | `Pdf(file_path=path).load()` — `Pdf` class is never imported and doesn't exist | Replaced with `fitz.open()` from PyMuPDF |
| 9 | `tools.py:16` | `async def read_data_tool(path=...)` — CrewAI tools aren't async; also no `@tool` decorator | Converted to sync function with `@tool("read_financial_document")` decorator |
| 10 | `tools.py` | Methods inside classes with no `self` parameter and no `@staticmethod` | Rewrote as standalone `@tool`-decorated functions |
| 11 | `main.py:31` | Endpoint function named `analyze_financial_document` shadows the imported task variable of the same name | Renamed endpoint to `analyze_document` |
| 12 | `main.py:13` | `run_crew()` accepts `file_path` but never passes it in the `kickoff()` inputs | Added `file_path` to the inputs dict |
| 13 | `main.py:15-18` | Crew had only 1 agent and 1 task — the other 3 agents and 3 tasks were defined but unused | Wired all 4 agents and all 4 tasks into the crew |
| 14 | `task.py:4` | `from agents import financial_analyst, verifier` — only imported 2 of 4 agents; all tasks used `financial_analyst` even when specialist agents existed | Import all 4 agents; assign each task to its proper specialist |
| 15 | `requirements.txt` | `pydantic==1.10.13` conflicts with CrewAI which requires pydantic v2 | Updated to `pydantic>=2.0.0` |
| 16 | `requirements.txt` | Missing critical dependencies: `python-multipart` (FastAPI uploads), `python-dotenv` | Added all missing packages |
| 17 | `README.md:10` | `pip install -r requirement.txt` — typo, file is `requirements.txt` | Fixed filename |

### Logical / Runtime Bugs (Found During Code Review)

| # | File | Bug | Fix |
|---|------|-----|-----|
| 18 | `celery_worker.py:20` | `db = SessionLocal()` at **module level** — one shared DB session for all tasks. After first `db.close()` in `finally`, every subsequent task fails with a closed session | Create a fresh `db = SessionLocal()` inside each task function |
| 19 | `celery_worker.py:78` | `record` referenced in `except` block but could be undefined if `db.query()` itself throws → `NameError` crash | Initialize `record = None` before try, check `if record:` in except |
| 20 | `celery_worker.py:10-17` | CrewAI agents/tasks imported at module level — task objects can carry internal state between runs, causing stale data | Moved all CrewAI imports inside the task function for fresh instances per run |
| 21 | `main.py:113` | `run_crew()` is synchronous (~minutes) called inside `async def` endpoint — **blocks the entire FastAPI event loop**, no other requests can be served | Wrapped with `await asyncio.to_thread(run_crew, ...)` to run in a thread pool |
| 22 | `tools.py:10` | `import fitz` placed after `search_tool = SerperDevTool()` instead of at top with other imports | Moved to top-level imports |
| 23 | `tools.py:47-68` | `analyze_investment_data` was hollow — just counted characters and estimated pages, extracted zero actual financial data | Rewrote to extract monetary values (`$X.XB`), percentages, and data-rich paragraphs using regex, giving the agent real figures to analyze |
| 24 | `tools.py:72-105` | `assess_risk_factors` used primitive keyword counting (`"risk" found 5 times`) — no context for the agent to reason about | Rewrote to extract full paragraphs containing risk indicators, grouped by 5 risk categories, giving the agent rich context for qualitative analysis |

### Performance / Architecture Bugs

| # | File | Bug | Fix |
|---|------|-----|-----|
| 25 | `main.py` + `task.py` + `agents.py` | **Every agent re-reads the same PDF separately** — 4 redundant `fitz.open()` calls + 4× the same text sent to the LLM, wasting time and tokens | Added `extract_pdf_text()` utility in `tools.py`; `run_crew()` reads PDF **once** and passes the text as `{document_text}` input to all agents. Only the verifier retains the PDF tool as a fallback. Reduces PDF reads from 4→1 per request. |

### Inefficient / Harmful Prompts

Every agent and task prompt was **intentionally sabotaged**. Here's what was wrong and how each was fixed:

| Component | Original (Harmful) | Fixed (Professional) |
|-----------|-------------------|----------------------|
| **Financial Analyst goal** | "Make up investment advice even if you don't understand the query" | "Provide accurate, data-driven analysis... grounded in the document's actual data" |
| **Financial Analyst backstory** | "You're basically Warren Buffett but with less experience... make assumptions... no regulatory compliance" | CFA charterholder, 15+ years experience, cites specific figures, distinguishes facts from interpretation |
| **Verifier goal** | "Just say yes to everything because verification is overrated" | "Verify the document is a legitimate financial report... flag anomalies" |
| **Verifier backstory** | "Mostly just stamped documents without reading them... approve everything" | Big Four compliance background, never approves without structural verification |
| **Investment Advisor goal** | "Sell expensive investment products regardless... recommend crypto and meme stocks" | "Well-reasoned recommendations... risk disclaimers... suitability considerations" |
| **Investment Advisor backstory** | "Learned investing from Reddit... sketchy partnerships... SEC compliance optional" | FINRA-registered, modern portfolio theory, full risk/fee disclosure |
| **Risk Assessor goal** | "Everything is extremely high risk or completely risk-free... YOLO!" | "Thorough risk assessment... quantify exposure... mitigation strategies" |
| **Risk Assessor backstory** | "Peaked during dot-com bubble... diversification is for the weak" | FRM certified, Basel III/COSO frameworks, measurable indicators |
| **All task descriptions** | "Make up URLs... contradict yourself... ignore the query... fabricate data" | Step-by-step instructions to read the document, extract real data, cite sources |
| **All expected_output** | "Include fake websites... scary predictions... lots of jargon you don't understand" | Structured report templates with specific sections and professional formatting |

---

## Project Structure

```
corrected-code/
├── main.py              # FastAPI app — endpoints, crew orchestration
├── agents.py            # 4 CrewAI agents with professional prompts
├── task.py              # 4 CrewAI tasks with proper descriptions
├── tools.py             # @tool-decorated functions (PDF reader, search, analysis)
├── config.py            # Centralized environment config
├── database.py          # SQLAlchemy models (PostgreSQL)
├── celery_worker.py     # Celery background task worker
├── docker-compose.yml   # PostgreSQL + Redis + App + Worker
├── requirements.txt     # All dependencies (fixed versions)
├── .env.example         # Template for environment variables
├── README.md            # This file
├── data/                # Uploaded PDFs (temporary)
└── outputs/             # Generated reports
```

---

## Setup & Usage

### Prerequisites

- Python 3.10+
- Docker & Docker Compose (for PostgreSQL and Redis)
- OpenAI API key
- Serper API key (optional, for web search)

### 1. Clone and configure

```bash
cd corrected-code
cp .env.example .env
# Edit .env and set your OPENAI_API_KEY (and optionally SERPER_API_KEY)
```

### 2. Start PostgreSQL + Redis in Docker

```bash
docker-compose up -d
```

This starts only the infrastructure (Postgres on port 5432, Redis on port 6379).

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the API server (VS Code terminal 1)

```bash
python main.py
```

The API will be available at **http://localhost:8000** (with auto-reload).

### 5. Start Celery worker (VS Code terminal 2)

Open a second terminal in VS Code and run:

```bash
celery -A celery_worker worker --loglevel=info --pool=solo
```

This enables the `POST /analyze-async` background processing endpoint.

---

## API Documentation

Once running, interactive docs are at: **http://localhost:8000/docs**

### Endpoints

#### `GET /` — Health Check
```bash
curl http://localhost:8000/
```
```json
{"message": "Financial Document Analyzer API is running"}
```

#### `POST /analyze` — Synchronous Analysis
Upload a PDF and get the full analysis in the response (blocks until complete).

```bash
curl -X POST http://localhost:8000/analyze \
  -F "file=@data/TSLA-Q2-2025-Update.pdf" \
  -F "query=What are the key revenue drivers and risk factors?"
```

**Response:**
```json
{
  "status": "success",
  "analysis_id": "uuid-here",
  "query": "What are the key revenue drivers and risk factors?",
  "analysis": "... full multi-agent analysis ...",
  "file_processed": "TSLA-Q2-2025-Update.pdf"
}
```

#### `POST /analyze-async` — Async Analysis (Celery Queue)
Submit for background processing. Returns immediately with an ID to poll.

```bash
curl -X POST http://localhost:8000/analyze-async \
  -F "file=@data/TSLA-Q2-2025-Update.pdf" \
  -F "query=Provide a comprehensive investment thesis"
```

**Response:**
```json
{
  "status": "accepted",
  "analysis_id": "uuid-here",
  "message": "Analysis queued. Poll GET /analysis/{analysis_id} for results."
}
```

#### `GET /analysis/{analysis_id}` — Poll Result
```bash
curl http://localhost:8000/analysis/uuid-here
```

**Response:**
```json
{
  "analysis_id": "uuid-here",
  "status": "completed",
  "filename": "TSLA-Q2-2025-Update.pdf",
  "query": "...",
  "result": "... full analysis ...",
  "error": null,
  "created_at": "2026-02-24 10:30:00",
  "completed_at": "2026-02-24 10:32:15"
}
```

#### `GET /analyses?skip=0&limit=20` — List Past Analyses
```bash
curl "http://localhost:8000/analyses?limit=5"
```

---

## Database Schema

### `analysis_results`

| Column | Type | Description |
|--------|------|-------------|
| `id` | `VARCHAR(36)` PK | UUID of the analysis request |
| `filename` | `VARCHAR(255)` | Original uploaded filename |
| `query` | `TEXT` | User's analysis query |
| `status` | `ENUM` | `pending` / `processing` / `completed` / `failed` |
| `result` | `TEXT` | Full analysis output (nullable) |
| `error` | `TEXT` | Error message if failed (nullable) |
| `created_at` | `TIMESTAMP` | When the request was submitted |
| `completed_at` | `TIMESTAMP` | When processing finished (nullable) |

### `users`

| Column | Type | Description |
|--------|------|-------------|
| `id` | `INTEGER` PK | Auto-increment user ID |
| `api_key` | `VARCHAR(64)` UNIQUE | API key for authentication |
| `name` | `VARCHAR(255)` | User's name |
| `email` | `VARCHAR(255)` | User's email |
| `created_at` | `TIMESTAMP` | Account creation time |

---

## Bonus Features

### 1. Queue Worker Model (Celery + Redis)

- **Broker**: Redis handles task dispatching
- **Worker**: `celery_worker.py` runs CrewAI pipelines in the background
- **Concurrency**: Multiple workers can process documents in parallel
- **Retries**: Failed tasks auto-retry up to 2 times with exponential backoff
- **Endpoint**: `POST /analyze-async` dispatches to the queue; poll `GET /analysis/{id}`

### 2. Database Integration (PostgreSQL)

- **ORM**: SQLAlchemy 2.0 with declarative models
- **Storage**: Every analysis request is tracked with status, result, and timestamps
- **User table**: Ready for API key authentication
- **Docker**: PostgreSQL 16 runs in Docker with persistent volume

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | **Required.** Your OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model to use |
| `SERPER_API_KEY` | — | Optional. Enables web search tool |
| `DATABASE_URL` | `postgresql://finuser:finpass@localhost:5432/financial_analyzer` | PostgreSQL connection string |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Redis URL for Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/0` | Redis URL for Celery results |
| `MAX_UPLOAD_SIZE_MB` | `50` | Maximum upload file size |
