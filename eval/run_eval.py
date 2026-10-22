"""Evaluate retrieval + grounding on eval/questions.json.

Usage:
    python eval/run_eval.py              # retrieval only (no LLM calls)
    python eval/run_eval.py --with-llm   # also generate answers and check them
"""
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "codelens.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from analysis.static import analyze  # noqa: E402
from rag.grounding import grounding  # noqa: E402
from rag.query_builder import build_queries  # noqa: E402
from rag.retrieve import retrieve  # noqa: E402

SWEEP = [round(0.30 + 0.05 * i, 2) for i in range(8)]  # 0.30 .. 0.65


def expected_sources(item):
    src = item.get("expected_source") or []
    return [src] if isinstance(src, str) else src


def run_retrieval(item):
    code = item.get("code", "")
    findings = analyze(code) if code else []
    started = time.perf_counter()
    queries = build_queries(code, item["problem"], findings)
    doc_chunks, _ = retrieve(queries)
    grounded, top = grounding(doc_chunks)
    return {
        "doc_chunks": doc_chunks, "grounded": grounded, "top_score": top,
        "latency_ms": (time.perf_counter() - started) * 1000,
    }


def run_llm(item):
    from assistant.services import run_answer, run_retrieval as pipeline_retrieve
    from assistant.models import QueryLog

    r = pipeline_retrieve({"code": item.get("code", ""), "problem_text": item["problem"], "action": "explain"})
    res = run_answer(QueryLog.objects.get(pk=r["query_id"]))
    a = res["answer"]
    text = " ".join([a["summary"], a["explanation"], a["fix_explanation"], a["general_notes"]])
    doc_ns = {c["n"] for c in r["doc_chunks"]}
    return {"keyword_hit": item.get("expected_keyword", "").lower() in text.lower(),
            "doc_citations": sorted(doc_ns & set(a["used_citations"]))}


def refusal_metrics(rows, threshold):
    inscope = [r for r in rows if r["answerable"]]
    outscope = [r for r in rows if not r["answerable"]]
    correct_refusal = sum(r["top_score"] < threshold for r in outscope) / max(len(outscope), 1)
    false_refusal = sum(r["top_score"] < threshold for r in inscope) / max(len(inscope), 1)
    return correct_refusal, false_refusal


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-llm", action="store_true")
    args = parser.parse_args()
    items = json.loads((ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))
    k = settings.TOP_K

    rows = []
    for item in items:
        res = run_retrieval(item)
        answerable = item.get("expect_grounded", True)
        titles = [c["title"] for c in res["doc_chunks"]]
        row = {
            "id": item["id"], "answerable": answerable, "problem": item["problem"],
            "top_score": res["top_score"], "grounded": res["grounded"], "latency_ms": round(res["latency_ms"], 1),
            "top_sources": titles[:3],
        }
        if answerable:
            exp = expected_sources(item)
            row["hit"] = any(t in exp for t in titles[:k])
            row["rank"] = next((i + 1 for i, t in enumerate(titles) if t in exp), None)
        if args.with_llm:
            row.update(run_llm(item))
        rows.append(row)

    print(f"\n{'id':<5}{'type':<8}{'top':>6}  {'grounded':<9}{'hit@'+str(k):<7}{'rank':<5}question")
    print("-" * 100)
    for r in rows:
        print(f"{r['id']:<5}{'in' if r['answerable'] else 'out':<8}{r['top_score']:>6.3f}  {str(r['grounded']):<9}"
              f"{str(r.get('hit', '')):<7}{str(r.get('rank') or ''):<5}{r['problem'][:60]}")

    inscope = [r for r in rows if r["answerable"]]
    hit_rate = sum(r["hit"] for r in inscope) / max(len(inscope), 1)
    mrr = statistics.mean(1 / r["rank"] if r["rank"] else 0 for r in inscope) if inscope else 0
    threshold = settings.GROUNDING_THRESHOLD
    correct_refusal, false_refusal = refusal_metrics(rows, threshold)
    latency = statistics.mean(r["latency_ms"] for r in rows)
    summary = {
        "questions": len(rows), "answerable": len(inscope), "out_of_scope": len(rows) - len(inscope),
        f"hit@{k}": round(hit_rate, 3), "mrr": round(mrr, 3), "threshold": threshold,
        "correct_refusal_rate": round(correct_refusal, 3), "false_refusal_rate": round(false_refusal, 3),
        "avg_retrieval_ms": round(latency, 1),
    }
    if args.with_llm:
        summary["keyword_hit_rate"] = round(sum(r["keyword_hit"] for r in inscope) / max(len(inscope), 1), 3)
        outs = [r for r in rows if not r["answerable"]]
        summary["out_of_scope_without_doc_citations"] = round(
            sum(not r["doc_citations"] for r in outs) / max(len(outs), 1), 3)

    print("\nSummary")
    for key, val in summary.items():
        print(f"  {key:<36}{val}")

    print("\nThreshold sweep (grounded = best doc cosine >= threshold)")
    print(f"  {'threshold':<11}{'correct refusal':<17}{'false refusal':<15}balanced acc")
    sweep, best = [], None
    for t in SWEEP:
        cr, fr = refusal_metrics(rows, t)
        bal = (cr + (1 - fr)) / 2
        sweep.append({"threshold": t, "correct_refusal": round(cr, 3), "false_refusal": round(fr, 3),
                      "balanced_accuracy": round(bal, 3)})
        # Prefer fewer false refusals on ties: wrongly saying "not in your docs" hurts the demo most.
        if best is None or (bal, -fr) > (best["balanced_accuracy"], -best["false_refusal"]):
            best = sweep[-1]
        print(f"  {t:<11.2f}{cr:<17.0%}{fr:<15.0%}{bal:.0%}")
    print(f"\nRecommended GROUNDING_THRESHOLD = {best['threshold']:.2f}")

    out = {"summary": summary, "sweep": sweep, "recommended_threshold": best["threshold"], "rows": rows}
    (ROOT / "eval" / "results.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("Wrote eval/results.json")


if __name__ == "__main__":
    main()
