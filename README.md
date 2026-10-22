# CodeLens RAG — AI Code Explainer & Debugging Assistant

**A web IDE that understands your whole project and your documentation, and shows you exactly where every answer comes from.**

Open a project folder (or a .zip), select code, and press **Explain** or **Debug**. CodeLens first shows you what it retrieved from your documentation and your own codebase (with scores), then Gemini answers using only that context, with clickable `[n]` citations, issue markers on the exact lines, and a diff of the fix. If your docs don't cover the question, it says so.

Hackathon Problem Statement 02 — *AI-Powered Programming Code Explainer and Debugging Assistant Using RAG*.

## Requirements → features

| # | Requirement | Where |
|---|---|---|
| 1 | Code input + problem description | Monaco editor (project files or **Paste mode**) + "Describe your problem" box — `templates/ide.html`, `static/js/ide.js` |
| 2 | Upload PDF/TXT knowledge base | Knowledge Base page, PyMuPDF extraction with page numbers, heading + monospace-code detection — `knowledge/services/extract.py` |
| 3 | RAG: extract, chunk, embed, semantic search | Heading-aware chunker that never splits code blocks, `all-MiniLM-L6-v2`, ChromaDB + BM25 hybrid with RRF — `knowledge/services/chunk.py`, `rag/` |
| 4 | Explain, find errors, recommend fixes from retrieved context | Gemini with JSON output, context-only rules — `assistant/prompts.py`, `assistant/llm.py` |
| 5 | Show source references | Inline `[n]` citations → modal with the full passage, query terms highlighted — `static/js/ai_panel.js` |
| 6 | Django backend | Apps `projects`, `knowledge`, `rag`, `analysis`, `assistant` |
| 7 | Interactive interface | 3-pane IDE: file tree, editor with gutter markers + hover, AI panel with inspector, issues, Monaco diff + Apply fix |
| 8 | Say when the KB lacks info | Grounding badge (threshold tuned by eval) + "General AI knowledge (unverified)" section; final verdict requires the answer to cite a doc |
| C2 | Retrieval shown **before** the answer | Two endpoints: `/api/retrieve` renders the Retrieval Inspector, then `/api/answer` (needs its `query_id`) |
| C3 | Never execute submitted code | Only `ast.parse` + pyflakes on source text — `analysis/static.py`, proven by `analysis/tests.py` |

Extras: symbol-aware code retrieval (definitions of classes/functions your selection uses are boosted), static checks for mutable defaults / `range(len(x)+1)` / `x[len(x)]`, Beginner / Expert / Hint-first modes, persistent LLM cache, automatic fallback model on 429/503, `.codelensignore` for project uploads.

## Skills (`/name`)

A skill is a `SKILL.md` file that tells CodeLens which knowledge-base files and web docs to use for a kind of work, plus how to answer. Install them on the **Skills** page (upload or write), then type `/` at the start of a Chat message or the problem box to pick one.

```markdown
---
name: django-backend
description: Django views, models, QuerySets and backend request pipelines
docs: [django_querysets, "python_*"]          # only these KB docs are searched (wildcards ok)
urls:                                         # fetched into the KB and searched with this skill
  - https://docs.djangoproject.com/en/5.1/topics/db/queries/
---
Instructions the assistant follows while the skill is active.
```

Samples in `demo_skills/` (installed by `load_demo`): `/python-debugging`, `/django-backend`, `/frontend-ui-ux`, `/agentic-ai`. URLs must be public http(s) pages; private/loopback addresses are refused.

## Architecture

```
 Browser (Bootstrap + Monaco)
   │  file tree │ editor │ AI panel
   ▼
 Django
   ├── projects/   upload folder/zip → store files → index code (ast chunks)
   ├── knowledge/  upload PDF/TXT → extract → chunk → embed
   ├── rag/        query builder → hybrid retrieve (vector + BM25, RRF) → grounding
   ├── analysis/   ast + pyflakes static findings (no execution)
   └── assistant/  prompt → Gemini → JSON validate → cache → response
   │
   ├── ChromaDB  (collections: docs, project_<id>)
   ├── SQLite    (Project, ProjectFile, Document, Chunk, QueryLog, CacheEntry)
   └── Gemini API
```

Debug flow: static analysis on the whole file → 2–4 queries (problem text, traceback line, identifiers, findings, code) → hybrid search over `docs` and `project_<id>` → **Retrieval Inspector rendered** → prompt with numbered context → Gemini JSON → validated (unknown citations stripped) → explanation, issues, diff.

## Setup

```bash
python -m venv venv && venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                                 # then set GEMINI_API_KEY (macOS/Linux: cp)
python manage.py migrate && python manage.py load_demo
python manage.py runserver
```

Open http://127.0.0.1:8000. Optional: `python manage.py warm_cache` pre-generates the demo answers so the demo survives rate limits, and `python manage.py test_llm` checks your key.

Other commands: `python manage.py search_docs "list comprehension"`, `python manage.py test knowledge analysis assistant`, `python eval/run_eval.py [--with-llm]`.

## Evaluation (retrieval only, `python eval/run_eval.py`)

22 questions over `demo_kb/`: 12 answerable (with expected source), 10 out-of-scope.

| Metric | Value |
|---|---|
| hit@6 (expected doc in top 6) | 100% |
| MRR | 1.00 |
| Correct refusal rate (out-of-scope → "not found") | 100% |
| False refusal rate (answerable → "not found") | 0% |
| Grounding threshold (chosen by sweep 0.30–0.65) | 0.30 |
| Avg retrieval latency (CPU, warm) | ~0.2 s |

Answerable questions scored ≥ 0.37 best-doc cosine and out-of-scope ones ≤ 0.25, so 0.30 separates them; 0.45 (the original default) wrongly refused 1 of 12.

## Before you present (reliability)

Free-tier models are sometimes slow or down, so the demo never depends on them:

```bash
python manage.py warm_cache   # pre-answers everything in demo_script.json (retries failures)
python manage.py demo_check   # READY / NOT CACHED per demo request + which models respond right now
```

Run both **after** your last change to the docs, skills or demo project (any change alters the prompts, which `demo_check` will flag), and again shortly before presenting. Cached requests answer in seconds even with no internet model available.

Live (uncached) questions are protected too:
- **Racing:** OpenRouter starts first; if it hasn't answered in `LLM_HEDGE_AFTER` (12 s) or fails, Gemini starts in parallel and the first valid answer wins.
- **Hard deadline:** after `LLM_DEADLINE` (60 s) the app shows a clearly labelled *sources-only* answer — the retrieved passages with citations plus static-analysis findings — with a **Retry** button. It never shows a blank error.

Edit `demo_script.json` to match what you will click during the demo.

## Demo script (3 minutes)

1. **Knowledge Base** page: 5 pre-indexed docs with chunk counts; try "Test retrieval".
2. IDE → open `demo_project`, `orders/views.py`: gutter shows static findings (unused import).
3. Select `customer_orders` (lines 22–27) → **Debug** → the Retrieval Inspector appears first: Django QuerySet docs + `class Order` from `models.py`.
4. Answer: issue on line 25 (`get()` → `filter()`), citation `[n]` → click → source passage with highlights.
5. Fix diff → **Apply fix** (editor buffer only).
6. Paste mode, empty editor, ask "How do I train a neural network in PyTorch?" → amber **Not found in your knowledge base**.
7. Upload a tiny TXT note on the Knowledge Base page, ask about it → cited immediately.
8. Metrics table above.

Planted bugs are documented in `demo_project/BUGS.md` (excluded from indexing by `demo_project/.codelensignore`).

## Safety notes

- Submitted code is only parsed (`ast.parse`, pyflakes). Nothing calls `exec`, `eval`, `subprocess` or imports user files.
- Model output is untrusted: JSON is validated, citation ids are checked against the retrieved context, and all model text is inserted with `textContent`.
- Secrets come only from `.env` (git-ignored). Keep real keys out of `.env.example`.
