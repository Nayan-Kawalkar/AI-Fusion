# CLAUDE.md — CodeLens RAG: AI Code Explainer & Debugging Assistant

> Project guide for Claude (and teammates). Read this fully before writing any code.
> Hackathon: Problem Statement No. 02 — "AI-Powered Programming Code Explainer and Debugging Assistant Using RAG"

---

## 1. What we are building

A **browser-based mini IDE served by Django**. The user opens a project folder (or uploads a .zip), browses files in a tree, views code in a Monaco editor, selects code, and asks the AI to **Explain** or **Debug** it.

Every answer is grounded in **two knowledge sources**:
1. **Documentation KB** — PDFs/TXT the user uploads (language docs, class notes).
2. **Project KB** — the user's own codebase, indexed by function/class.

The UI shows **what was retrieved first** (Retrieval Inspector), then the AI answer with **clickable citations**, highlighted problem lines, and a **diff** of the suggested fix. If the docs don't cover the question, the app **says so clearly**.

**Pitch line:** *"A web IDE that understands your whole project and your documentation, and shows you exactly where every answer comes from."*

---

## 2. Non-negotiable requirements (map every feature to these)

| # | Requirement (from brief) | How we satisfy it | Phase |
|---|---|---|---|
| 1 | Code input + problem description | Monaco editor (project files or paste mode) + "Describe your problem" box | 1, 4 |
| 2 | Upload PDF/TXT knowledge base | Docs upload page, PyMuPDF extraction | 2 |
| 3 | RAG pipeline: extract, chunk, embed, semantic search | Chunker + sentence-transformers + ChromaDB (+ BM25 hybrid) | 2, 3 |
| 4 | Explain code, suggest errors, recommend fixes using retrieved context | Gemini with structured JSON output, context injected | 4 |
| 5 | Show source references | Inline [n] citations → click highlights source passage | 4, 5 |
| 6 | Django backend for requests, processing, retrieval, AI | All logic in Django apps/services | all |
| 7 | Interactive interface: code, explanation, issues, fixes | 3-pane IDE layout, gutter markers, diff view | 5 |
| 8 | Indicate when KB lacks info | Grounding threshold → "Not found in your knowledge base" badge, split answer sections | 4 |
| C1 | Use own notes / public docs | Pre-loaded demo KB (Python docs subset + notes) | 7 |
| C2 | **Retrieval must be demonstrated before the answer** | Retrieval Inspector renders chunks + scores BEFORE answer streams | 3, 5 |
| C3 | **Never execute submitted code** | Only `ast.parse` / pyflakes on source text. No `exec`, `eval`, `subprocess` on user code. Ever. | 3 |

---

## 3. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python 3.11+, Django 5.x | Plain Django views returning JSON + one template-based SPA page |
| Frontend | HTML, CSS, Bootstrap 5, vanilla JS | Monaco Editor via CDN (jsdelivr), no React needed |
| LLM | Gemini API via `google-genai` SDK | Model name from env `GEMINI_MODEL` (use the current Flash model) |
| Embeddings | `sentence-transformers` — `all-MiniLM-L6-v2` | Local, free, no rate limits. Swap to Gemini embeddings only if time allows |
| Vector store | ChromaDB (`PersistentClient`, path `./chroma_data`) | Two collections: `docs`, `project_<id>` |
| Keyword search | `rank_bm25` | Hybrid with vectors for exact identifiers (`ValueError`, `QuerySet.filter`) |
| PDF/TXT | PyMuPDF (`fitz`) | Keep page numbers |
| Static analysis | Python `ast`, `pyflakes` | Analyzes source text only, never runs it |
| DB | SQLite | Default Django DB is enough |

`requirements.txt`:
```
django>=5.0
google-genai
chromadb
sentence-transformers
rank_bm25
pymupdf
pyflakes
python-dotenv
```

`.env` (never commit):
```
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
GROUNDING_THRESHOLD=0.45
TOP_K=6
```

---

## 4. Architecture

```
 Browser (Bootstrap + Monaco)
   │  file tree │ editor │ AI panel
   ▼
 Django
   ├── projects/   upload folder/zip → store files → index code (ast chunks)
   ├── knowledge/  upload PDF/TXT → extract → chunk → embed
   ├── rag/        query builder → hybrid retrieve → grounding check
   ├── analysis/   ast + pyflakes static findings (no execution)
   └── assistant/  prompt build → Gemini → JSON validate → cache → response
   │
   ├── ChromaDB  (collections: docs, project_<id>)
   ├── SQLite    (Project, ProjectFile, Document, Chunk, Query, Answer)
   └── Gemini API
```

**Request flow for "Debug this selection":**
1. Frontend sends `{project_id, file_path, selection, start_line, problem_text, mode}`.
2. `analysis` runs ast/pyflakes on the full file → findings with line numbers.
3. `rag.query_builder` builds search queries from: problem text + imports + called names + error types + findings.
4. `rag.retrieve` runs hybrid search on `docs` and `project_<id>` → top-K chunks with scores.
5. **Return retrieval results to UI immediately** (endpoint 1) → Retrieval Inspector renders.
6. `rag.grounding` decides `grounded: true/false` from top doc score vs threshold.
7. `assistant` builds the prompt, calls Gemini, validates JSON (endpoint 2).
8. UI renders explanation, issues (gutter markers), diff, citations.

Two separate endpoints for steps 5 and 7 is deliberate — it **proves retrieval happens before generation** (constraint C2).

---

## 5. Directory structure

```
codelens/
├── CLAUDE.md
├── manage.py
├── requirements.txt
├── .env.example
├── codelens/                # settings, urls
├── projects/                # Project, ProjectFile models; upload + file tree views
├── knowledge/               # Document, Chunk models; doc upload views
│   └── services/extract.py, chunk.py
├── rag/
│   ├── embeddings.py        # singleton model loader
│   ├── store.py             # Chroma wrapper
│   ├── code_indexer.py      # ast-based chunking of project files
│   ├── query_builder.py
│   ├── retrieve.py          # hybrid vector + BM25, score fusion
│   └── grounding.py
├── analysis/
│   └── static.py            # ast + pyflakes, returns findings
├── assistant/
│   ├── prompts.py
│   ├── llm.py               # Gemini client, retries, cache
│   ├── schema.py            # JSON schema + validation
│   └── views.py             # /api/retrieve, /api/answer
├── templates/
│   ├── base.html
│   ├── ide.html             # main 3-pane page
│   └── knowledge.html
├── static/
│   ├── css/ide.css
│   └── js/ide.js, tree.js, ai_panel.js, diff.js
├── demo_kb/                 # pre-loaded docs for demo
├── demo_project/            # buggy sample project for demo
└── eval/
    ├── questions.json
    └── run_eval.py
```

---

## 6. Data models

```python
class Project(models.Model):
    name = CharField; created_at = DateTimeField(auto_now_add=True)
    indexed = BooleanField(default=False)

class ProjectFile(models.Model):
    project = FK(Project); path = CharField; language = CharField
    content = TextField; size = IntegerField

class Document(models.Model):
    title = CharField; file = FileField; kind = CharField  # pdf/txt
    pages = IntegerField; uploaded_at = DateTimeField(auto_now_add=True)
    indexed = BooleanField(default=False)

class Chunk(models.Model):
    source_type = CharField  # "doc" | "code"
    document = FK(Document, null=True); project_file = FK(ProjectFile, null=True)
    text = TextField; page = IntegerField(null=True)
    heading = CharField(blank=True)          # section title or "class Order"
    start_line = IntegerField(null=True); end_line = IntegerField(null=True)
    chroma_id = CharField(unique=True)

class QueryLog(models.Model):
    project = FK(Project, null=True); selection = TextField; problem = TextField
    mode = CharField; retrieved = JSONField; grounded = BooleanField
    answer = JSONField(null=True); latency_ms = IntegerField; created_at = ...
```

---

## 7. Core logic specs

### 7.1 Document chunking (`knowledge/services/chunk.py`)
- Extract per page with PyMuPDF; keep page number.
- Target ~600 tokens (~2400 chars), overlap ~80 tokens.
- **Never split inside a code block.** Detect indented/monospace blocks or fenced ``` blocks and keep them whole.
- Attach nearest preceding heading as `heading`.

### 7.2 Code indexing (`rag/code_indexer.py`)
- Python files: `ast.parse` → one chunk per top-level function, class, and method (with source lines via `ast.get_source_segment`, `lineno`, `end_lineno`). Module-level leftover code = one chunk.
- Non-Python files: fixed line windows (60 lines, 10 overlap).
- If `ast.parse` fails (syntax error), fall back to line windows — and still index.
- Skip: `.git`, `node_modules`, `venv`, `.venv`, `__pycache__`, `dist`, `build`, binaries, files > 200 KB. Limit project upload to 20 MB.

### 7.3 Static analysis (`analysis/static.py`)
- `ast.parse` → catch `SyntaxError` → finding with line/col/message.
- `pyflakes.api.check` on source string with a custom reporter → undefined names, unused imports, redefinitions.
- Output: `[{line, severity, code, message}]`.
- **Must not import, exec, eval or subprocess the user's code.** Add a comment stating this at top of the file.

### 7.4 Query building (`rag/query_builder.py`)
Produce 2–4 queries:
1. User's problem text (if any).
2. Key identifiers: imports, attribute calls (`df.merge`, `objects.filter`), exception names.
3. Static findings messages.
4. Traceback last line if user pasted one.

### 7.5 Hybrid retrieval (`rag/retrieve.py`)
- For each query: vector top-10 from Chroma + BM25 top-10 over the same collection.
- Fuse with Reciprocal Rank Fusion (k=60); dedupe; keep cosine similarity of each chunk for display.
- Return top `TOP_K` from docs and top 4 from project code, each: `{id, source_type, title/path, page/lines, heading, text, score}`.

### 7.6 Grounding check (`rag/grounding.py`)
- `grounded = max(doc_scores) >= GROUNDING_THRESHOLD` (tune in Phase 7).
- Pass `grounded` into the prompt. If false, model must put general knowledge only in `general_notes` and must not cite docs.

### 7.7 Prompt + JSON schema (`assistant/prompts.py`, `schema.py`)
System rules:
- Use ONLY the provided context for documentation-based claims; cite as `[n]` matching context ids.
- If context doesn't support a claim, put it in `general_notes`, never cite it.
- Line numbers refer to the original file.
- Mode `hint`: give hints in `hints`, leave `fixed_code` empty.
- Respond with JSON only.

Schema:
```json
{
  "summary": "string",
  "explanation": "string with [n] citations",
  "issues": [{"line": 12, "severity": "error|warning|info", "title": "string", "reason": "string", "citations": [1]}],
  "fixed_code": "string",
  "fix_explanation": "string",
  "hints": ["string"],
  "general_notes": "string",
  "grounded": true,
  "used_citations": [1, 3]
}
```
- Validate; on parse failure retry once with "Return valid JSON only". Strip unknown citation ids.

### 7.8 LLM client (`assistant/llm.py`)
- `google-genai` client, `response_mime_type="application/json"`.
- Cache by hash(prompt) in SQLite or a dict + JSON file → demo never breaks on rate limits.
- Retry with backoff on 429/5xx (max 3).

---

## 8. API endpoints

| Method | URL | Purpose |
|---|---|---|
| POST | `/api/projects/upload` | multipart folder files (webkitdirectory) or zip → create Project |
| POST | `/api/projects/<id>/index` | index code into `project_<id>` |
| GET | `/api/projects/<id>/tree` | nested file tree JSON |
| GET | `/api/projects/<id>/file?path=` | file content |
| POST | `/api/docs/upload` | PDF/TXT upload → extract, chunk, embed |
| GET | `/api/docs` | list docs + chunk counts |
| POST | `/api/analyze` | static findings for given code |
| POST | `/api/retrieve` | **step 1**: returns retrieved chunks + scores + grounded flag + query_id |
| POST | `/api/answer` | **step 2**: takes query_id, returns AI JSON answer |
| GET | `/api/chunk/<chroma_id>` | full chunk text for citation popup |

Use CSRF token from cookie in JS fetch calls.

---

## 9. UI layout (`templates/ide.html`)

```
┌──────────────────────────────────────────────────────────────────────┐
│ CodeLens  [Open Folder] [Upload .zip] [Knowledge Base]   Mode: ▾     │
├────────────┬──────────────────────────────┬──────────────────────────┤
│ File tree  │ Monaco editor                │ AI panel                 │
│ ▸ app/     │  red/yellow gutter markers   │ ① Retrieval Inspector    │
│   models.py│  hover = issue reason        │   chunk cards + score bar│
│   views.py │                              │ ② Grounding badge        │
│            │  [Explain] [Debug] on select │ ③ Explanation [1][2]     │
│            │                              │ ④ Issues list            │
│            │ Problem: [_______________]   │ ⑤ Fix diff (Monaco diff) │
│            │                              │ ⑥ General notes (unverified)│
└────────────┴──────────────────────────────┴──────────────────────────┘
```
- Also a **Paste mode** tab (no project) so requirement 1 works standalone.
- Grounding badge: green "Grounded in your docs" / amber "Not found in your knowledge base — answer uses general AI knowledge".
- Citation click → modal with chunk text, source, page/lines, query terms highlighted.
- Diff: `monaco.editor.createDiffEditor`.
- Mode dropdown: Beginner / Expert / Hint-first.

---

## 10. Phase-wise implementation plan

Each phase ends with a working, demoable app. **Do not start a phase until the previous one's checklist passes.** If time is short, stop after Phase 4 and polish — that already meets all 8 requirements.

### Phase 0 — Setup (≈5% of time)
- [ ] Django project + apps (`projects`, `knowledge`, `rag`, `analysis`, `assistant`)
- [ ] `requirements.txt`, `.env.example`, `.gitignore` (.env, chroma_data, media, db.sqlite3)
- [ ] Gemini "hello" call works from a management command
- [ ] Embedding model loads once (module-level singleton)
**Done when:** `python manage.py runserver` serves a blank IDE page and `python manage.py test_llm` prints a Gemini reply.

### Phase 1 — Project open + editor (≈10%)
- [ ] Folder upload via `<input type="file" webkitdirectory multiple>` + zip upload
- [ ] Skip rules + size limits (7.2)
- [ ] File tree endpoint + JS tree; click opens file in Monaco with language detection
- [ ] Paste-mode tab
**Done when:** open `demo_project/`, click files, see code highlighted.

### Phase 2 — Documentation KB (≈15%)
- [ ] Upload PDF/TXT; extract with PyMuPDF keeping page numbers
- [ ] Chunker (7.1) with code-block protection
- [ ] Embed + store in Chroma `docs` with metadata; `Chunk` rows in SQLite
- [ ] Knowledge page lists docs, chunk count, indexed status
**Done when:** uploading a 20-page PDF produces sensible chunks; a test script returns relevant chunks for "list comprehension".

### Phase 3 — Retrieval + static analysis (≈20%)
- [ ] Code indexer (7.2) → `project_<id>` collection
- [ ] Static analysis (7.3) + `/api/analyze`; markers appear in Monaco gutter
- [ ] Query builder (7.4), hybrid retrieval with RRF (7.5), grounding (7.6)
- [ ] `/api/retrieve` returns chunks + scores; **Retrieval Inspector** renders cards
**Done when:** selecting buggy code shows relevant doc chunks AND related project functions with scores — before any LLM call exists.

### Phase 4 — Generation (≈20%) — *minimum viable submission ends here*
- [ ] Prompt + schema (7.7), LLM client with cache + retry (7.8)
- [ ] `/api/answer`; render summary, explanation, issues, fixed code
- [ ] Inline `[n]` citations clickable → chunk modal
- [ ] Grounding badge + `general_notes` section for ungrounded answers
- [ ] QueryLog saved
**Done when:** Debug on demo bug gives correct issue with line number + citation; an off-topic question shows the amber "not found" badge.

### Phase 5 — UI polish (≈15%)
- [ ] Monaco diff view for fix + "Apply fix" (updates editor buffer only, not disk)
- [ ] Hover tooltips on issue lines
- [ ] Mode dropdown (Beginner / Expert / Hint-first) wired to prompt
- [ ] Loading states: "Retrieving…" → inspector → "Generating…"
- [ ] Empty states, error toasts, responsive on 1366px laptop screens
**Done when:** a non-teammate can use it without explanation.

### Phase 6 — Evaluation (≈5%)
- [ ] `eval/questions.json`: ~20 items, 10 answerable from demo KB (with expected source), 10 out-of-scope
- [ ] `eval/run_eval.py`: retrieval hit@K, correct-refusal rate, avg latency
- [ ] Tune `GROUNDING_THRESHOLD` from results; put numbers in README + final slide
**Done when:** a printed table of metrics exists.

### Phase 7 — Demo prep (≈10%)
- [ ] `demo_kb/`: Python docs subset (errors/exceptions, data structures) + Django querysets page + one notes TXT
- [ ] `demo_project/`: small Django/Python app with 3 planted bugs (off-by-one, wrong queryset method, mutable default arg)
- [ ] Management command `load_demo` to pre-index everything
- [ ] Warm the LLM cache by running the demo flow once
- [ ] Record a backup screen video
- [ ] README: setup in ≤5 commands, architecture image, metrics, screenshots
**Done when:** full demo runs offline-from-cache in under 3 minutes.

### Stretch (only if everything above is done)
- Electron/pywebview wrapper → "also runs as a desktop app"
- Gemini embeddings as an option, compare in eval
- Export answer as PDF/Markdown
- Session history sidebar

---

## 11. Demo script (3 minutes)

1. Knowledge Base page: show pre-indexed docs + chunk counts (15s)
2. Open `demo_project/`, click `orders/views.py`, gutter shows static findings (20s)
3. Select buggy function → Debug → **Retrieval Inspector appears first** with doc chunks + related `models.py` class (30s)
4. Answer: issue on exact line, citation [1] → click → source passage highlighted (40s)
5. Diff view → Apply fix (15s)
6. Ask something not in docs → amber "Not found in your knowledge base" (20s)
7. Upload a tiny TXT note live, ask about it → instantly cited (25s)
8. Metrics slide (15s)

---

## 12. Rules for Claude when coding this project

- **Never execute user-submitted code** — no `exec`, `eval`, `compile(...,'exec')` + run, `subprocess`, `importlib` on uploaded files.
- Keep business logic in `services`/module functions, not in views.
- Load the embedding model and Chroma client once (module-level singletons).
- Every chunk stored must carry metadata needed for citations (source, page or lines, heading).
- The answer endpoint must never be callable without a prior retrieve (`query_id` required).
- LLM output is untrusted: validate JSON, escape before inserting into HTML (`textContent`, not `innerHTML`, for model text).
- Secrets only from `.env`. Never hardcode API keys.
- Prefer small, working increments; keep the app runnable after every change.
- Write brief docstrings; no over-engineering (no Celery, no Docker unless asked).

---

## 13. Commands

```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # add GEMINI_API_KEY
python manage.py migrate
python manage.py load_demo
python manage.py runserver
python eval/run_eval.py
```

---

## 14. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Gemini rate limit / outage during demo | Response cache + pre-warmed demo + backup video |
| Slow embedding on large PDFs | Local MiniLM, batch encode, pre-index demo KB |
| Bad retrieval for code queries | Hybrid BM25 + identifier-based query building |
| Model cites things not in context | Strict prompt, strip invalid citation ids, grounding threshold |
| Huge uploaded project | Skip rules, 200 KB/file and 20 MB/project limits |
| Team merge conflicts | Split by app: frontend / knowledge+rag / assistant+analysis |

---

## 15. Phase-wise prompts for Claude Code

Copy-paste one prompt per phase into Claude Code, run it from the project root (where this CLAUDE.md lives). Wait for the phase to pass its checklist before sending the next one. Start a fresh session (`/clear`) between phases to keep context clean — CLAUDE.md is re-read automatically.

### Prompt 0 — Setup
```
Read CLAUDE.md fully. Implement Phase 0 only (section 10).

Create the Django project "codelens" with apps: projects, knowledge, rag, analysis, assistant.
Add requirements.txt (section 3), .env.example, and a .gitignore that excludes .env, chroma_data/, media/, db.sqlite3, venv/.
Load settings from .env using python-dotenv.
Create rag/embeddings.py with a module-level singleton that loads all-MiniLM-L6-v2 once.
Create assistant/llm.py with a minimal Gemini client using the google-genai SDK, model from GEMINI_MODEL env var.
Add a management command `test_llm` that sends "Say hello" and prints the reply.
Add templates/base.html (Bootstrap 5 via CDN) and an empty templates/ide.html served at "/".

Do not build anything from later phases.
When finished, run migrations, run `python manage.py check`, and tell me the exact commands to verify the Phase 0 "Done when" criteria.
```

### Prompt 1 — Project open + editor
```
Read CLAUDE.md. Implement Phase 1 only.

Models: Project, ProjectFile (section 6). Run migrations.
Endpoints (section 8): POST /api/projects/upload (accepts multiple files from <input webkitdirectory> with relative paths, OR a single .zip), GET /api/projects/<id>/tree, GET /api/projects/<id>/file?path=.
Apply skip rules and size limits from section 7.2 (skip .git, node_modules, venv, __pycache__, binaries, files >200KB, project >20MB). Store text content in ProjectFile.
Frontend (section 9): 3-pane layout in ide.html. Left = collapsible file tree (static/js/tree.js). Center = Monaco editor loaded from cdn.jsdelivr.net, language detected from extension. Right = empty AI panel placeholder.
Header buttons: "Open Folder" and "Upload .zip".
Add a "Paste mode" tab with an empty Monaco editor and a "Describe your problem" textarea.
Include CSRF token handling in fetch calls.

Also create demo_project/ — a small Python/Django-style app with exactly 3 planted bugs: off-by-one in a loop, wrong Django queryset method, and a mutable default argument. Document the bugs in demo_project/BUGS.md (for us, not for indexing).

Verify by uploading demo_project/ and confirm files open in the editor.
```

### Prompt 2 — Documentation knowledge base
```
Read CLAUDE.md. Implement Phase 2 only.

Models: Document, Chunk (section 6). Migrate.
knowledge/services/extract.py: PyMuPDF extraction per page for PDF; TXT read as page 1 (split long TXT into pseudo-pages of ~3000 chars).
knowledge/services/chunk.py: follow section 7.1 exactly — ~2400 chars, ~300 char overlap, never split inside code blocks (fenced ``` blocks or runs of indented lines), attach the nearest preceding heading.
rag/store.py: ChromaDB PersistentClient at ./chroma_data with helpers get_collection(name), add_chunks(collection, chunks), query(collection, embedding, k). Use cosine distance and convert to similarity = 1 - distance.
On upload: extract → chunk → batch-embed → store in Chroma collection "docs" with metadata {source_type:"doc", title, page, heading, chunk_db_id} and create Chunk rows.
Endpoints: POST /api/docs/upload, GET /api/docs.
Page templates/knowledge.html: upload form, list of documents with page count, chunk count, indexed status.
Add a management command `search_docs "<query>"` that prints top 5 chunks with scores, title, page.

Write a small unit test for the chunker proving a code block is never split.
Run the test and the search command against a sample PDF/TXT and show me the output.
```

### Prompt 3 — Code indexing, static analysis, retrieval
```
Read CLAUDE.md. Implement Phase 3 only. This is the most important phase — be careful.

1. rag/code_indexer.py per section 7.2: ast-based chunks for Python (functions, classes, methods with start/end lines via lineno/end_lineno and ast.get_source_segment), line windows for other files and for files with syntax errors. Store in Chroma collection "project_<id>" with metadata {source_type:"code", path, heading (e.g. "class Order" / "def save_order"), start_line, end_line, chunk_db_id}. Endpoint POST /api/projects/<id>/index; set Project.indexed=True. Trigger indexing automatically after upload.

2. analysis/static.py per section 7.3: ast.parse for SyntaxError + pyflakes.api.check with a custom reporter. Return [{line, col, severity, code, message}]. Put a comment at the top: this module never executes user code. Do NOT use exec, eval, subprocess, or import user files. Endpoint POST /api/analyze. In the frontend, when a Python file opens, call it and show Monaco gutter markers (monaco.editor.setModelMarkers).

3. rag/query_builder.py per section 7.4 and rag/retrieve.py per section 7.5: vector top-10 + BM25 (rank_bm25, build/cache the BM25 index per collection from Chunk rows) top-10, fuse with Reciprocal Rank Fusion k=60, dedupe, keep cosine similarity for display. Return top TOP_K doc chunks + top 4 code chunks.

4. rag/grounding.py per section 7.6.

5. Model QueryLog (section 6). Endpoint POST /api/retrieve: input {project_id?, file_path?, code, start_line, problem_text, mode}. Runs static analysis + query building + retrieval + grounding, saves a QueryLog, returns {query_id, queries, findings, doc_chunks, code_chunks, grounded, top_score}.

6. Frontend: on selecting code, show [Explain] [Debug] buttons. Clicking calls /api/retrieve and renders the Retrieval Inspector in the right panel: one card per chunk with source (title+page or path+lines), heading, a score bar, and a text preview. Show the grounding badge (green/amber) from section 9. Do NOT call the LLM yet.

Verify with demo_project: select each planted bug and confirm relevant doc chunks and related project functions appear. Show me the retrieved results for one bug.
```

### Prompt 4 — Generation with citations and grounding
```
Read CLAUDE.md. Implement Phase 4 only.

1. assistant/schema.py: the JSON schema from section 7.7 and a validate_answer() that fills missing fields with defaults and removes citation numbers that don't exist in the provided context.

2. assistant/prompts.py: build the prompt from section 7.7 rules. Number the context blocks [1]..[n] (doc chunks first, then code chunks) with their source labels. Include the user's code with real line numbers prefixed (starting from start_line), static findings, problem text, mode (beginner / expert / hint), and the grounded flag. If grounded is false, instruct the model to put general knowledge only in general_notes and to not cite docs.

3. assistant/llm.py: response_mime_type="application/json", retry with backoff on 429/5xx (max 3), one repair retry on invalid JSON, and a persistent cache keyed by sha256 of the full prompt (store in a JSON file or a CacheEntry model).

4. Endpoint POST /api/answer: input {query_id}. Must reject requests without a valid query_id from /api/retrieve. Loads the stored retrieval, calls the LLM, validates, saves answer + latency to QueryLog, returns the answer JSON.

5. Endpoint GET /api/chunk/<chroma_id> returning full chunk text + metadata.

6. Frontend (static/js/ai_panel.js): after the Retrieval Inspector renders, automatically call /api/answer and render below it: summary, explanation with [n] turned into clickable badges, issues list (click → editor jumps to line), fixed code block, fix explanation, hints (hint mode), and a clearly labeled "General AI knowledge (unverified)" section for general_notes. Clicking a citation opens a Bootstrap modal with the full chunk text and source. Render all model text with textContent, never innerHTML.

Verify: Debug on each demo bug gives the right line + a citation; asking "How do I train a neural network in PyTorch?" with no PyTorch docs shows the amber not-found badge and no doc citations. Show me both responses.
```

### Prompt 5 — UI polish
```
Read CLAUDE.md. Implement Phase 5 only.

- Fix diff: render fixed_code against the original selection using monaco.editor.createDiffEditor in the AI panel (or a modal on small screens). Add "Apply fix" that replaces the selection in the editor buffer only — never writes to disk or the database.
- Issue hover: register a Monaco hover provider showing issue title + reason on affected lines; merge with static-analysis markers (AI issues = different color).
- Mode dropdown in header (Beginner / Expert / Hint-first) sent with every request.
- Loading states: "Retrieving context…" spinner → inspector → "Generating answer…" skeleton → answer. Disable buttons while running.
- Error toasts for failed uploads, LLM errors, empty selection.
- Empty states: no project open, no docs uploaded (with link to Knowledge Base page).
- Layout must fit a 1366x768 laptop screen without horizontal scroll; panels resizable with simple drag handles.
- Clean, consistent styling in static/css/ide.css: dark editor theme, readable AI panel, consistent spacing.

Don't change backend logic except where needed for these features. Give me a short checklist of what to click to test each item.
```

### Prompt 6 — Evaluation
```
Read CLAUDE.md. Implement Phase 6 only.

Create eval/questions.json with ~20 items based on the files in demo_kb/ and demo_project/:
- 10 answerable: {id, code (optional), problem, expected_source (doc title or file path), expected_keyword}
- 10 out-of-scope (topics not in demo_kb): {id, problem, expect_grounded:false}

Create eval/run_eval.py as a Django management command `run_eval` (or a script using django.setup()) that, without calling the LLM by default:
- runs retrieval for each item
- computes retrieval hit@K (expected_source appears in top-K), correct-refusal rate (grounded flag false for out-of-scope), false-refusal rate, and avg retrieval latency
- with --with-llm, also calls the answer pipeline and checks expected_keyword appears in the answer and that out-of-scope answers contain no doc citations
- prints a clean table and writes eval/results.json

Then sweep GROUNDING_THRESHOLD from 0.30 to 0.65 in 0.05 steps, print the refusal metrics for each, and recommend the best value. Update .env.example with it.
```

### Prompt 7 — Demo prep
```
Read CLAUDE.md. Implement Phase 7 only.

- Populate demo_kb/ with TXT files written from scratch covering: Python exceptions and common errors, list/dict operations and mutable default arguments, loops and range() off-by-one pitfalls, Django QuerySet methods (get vs filter vs first, etc.). Write original explanatory text in your own words, organized with headings and code examples, ~2-4 pages each. Add a short "my_class_notes.txt" too.
- Management command `load_demo`: wipes Chroma + related DB rows, indexes demo_kb/ and demo_project/, prints a summary.
- Management command `warm_cache`: runs retrieve + answer for each planted bug and the out-of-scope demo question so the demo works from cache.
- README.md: one-paragraph pitch, features list mapped to the 8 requirements, architecture diagram (ASCII from CLAUDE.md), setup in ≤5 commands, eval results table from eval/results.json, demo script (section 11), screenshots placeholders.
- Do a final pass for: no hardcoded secrets, no user-code execution anywhere (grep for exec/eval/subprocess and report), DEBUG settings sane, requirements.txt complete.

Run load_demo and warm_cache and report the output.
```

### Utility prompts (use anytime)

**Bug fix**
```
Read CLAUDE.md. Something is broken: <paste error / describe behavior>.
Find the root cause, fix it with the smallest change, and tell me what was wrong. Don't refactor unrelated code.
```

**Review before submission**
```
Read CLAUDE.md. Review the whole project against section 2 (requirements table) and section 12 (rules).
For each requirement, tell me: met / partly met / missing, with the file that implements it.
List any rule violations (especially user-code execution or unescaped model output). Fix only the critical ones after showing me the list.
```

**Stretch: desktop wrapper**
```
Read CLAUDE.md. All phases are done. Add an optional desktop launcher using pywebview: desktop.py starts the Django dev server in a background thread and opens the app in a native window. Add it to README as "optional desktop mode". Don't change any existing behavior.
```
