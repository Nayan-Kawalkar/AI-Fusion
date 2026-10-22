"""Extract text from PDF (PyMuPDF) and TXT files, keeping page numbers.

PDF headings (larger / bold short lines) are emitted as "## Heading" lines and
monospace lines are indented by 4 spaces so the chunker treats them as code.
"""
from collections import Counter

MONO_HINTS = ("mono", "courier", "consol", "menlo", "code")
TXT_PAGE_CHARS = 3000


def _is_mono(span):
    return any(h in span["font"].lower() for h in MONO_HINTS) or bool(span["flags"] & 8)


def extract_pdf(path):
    """Return [(page_number, text)] for a PDF."""
    import pymupdf

    doc = pymupdf.open(path)
    try:
        page_dicts = [page.get_text("dict") for page in doc]
    finally:
        doc.close()

    # Body font size = the size covering the most characters.
    sizes = Counter()
    for d in page_dicts:
        for b in d["blocks"]:
            for line in b.get("lines", []):
                for s in line["spans"]:
                    sizes[round(s["size"], 1)] += len(s["text"].strip())
    body = sizes.most_common(1)[0][0] if sizes else 10.0

    pages = []
    for page_no, d in enumerate(page_dicts, start=1):
        blocks_out = []
        for b in d["blocks"]:
            if b.get("type") != 0:
                continue
            lines_out = []
            for line in b["lines"]:
                spans = [s for s in line["spans"] if s["text"].strip()]
                text = "".join(s["text"] for s in line["spans"]).rstrip()
                if not spans:
                    continue
                size = max(s["size"] for s in spans)
                if all(_is_mono(s) for s in spans):
                    char_w = max(size * 0.6, 1.0)
                    extra = max(0, round((line["bbox"][0] - b["bbox"][0]) / char_w))
                    lines_out.append("    " + " " * extra + text.strip())
                elif len(text) < 120 and (
                    size >= body * 1.15 or (all(s["flags"] & 16 for s in spans) and len(text) < 80)
                ):
                    lines_out.append("## " + text.strip())
                else:
                    lines_out.append(text)
            if lines_out:
                blocks_out.append("\n".join(lines_out))
        pages.append((page_no, "\n\n".join(blocks_out)))
    return pages


def split_pseudo_pages(text, size=TXT_PAGE_CHARS):
    """Split long text into ~size-char pages at blank lines outside code blocks."""
    lines = text.splitlines()
    pages, cur, cur_len, in_fence = [], [], 0, False

    def next_nonblank(i):
        for j in range(i + 1, len(lines)):
            if lines[j].strip():
                return lines[j]
        return ""

    def indented(s):
        return s.startswith("    ") or s.startswith("\t")

    prev_nonblank = ""
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_fence = not in_fence
        cur.append(line)
        cur_len += len(line) + 1
        if line.strip():
            prev_nonblank = line
        elif (
            cur_len >= size
            and not in_fence
            and not indented(prev_nonblank)
            and not indented(next_nonblank(i))
        ):
            pages.append("\n".join(cur).strip("\n"))
            cur, cur_len = [], 0
    if "".join(cur).strip():
        pages.append("\n".join(cur).strip("\n"))
    return [(n, p) for n, p in enumerate(pages, start=1)] or [(1, "")]


def extract_txt(path):
    with open(path, "rb") as f:
        text = f.read().decode("utf-8", errors="replace")
    return split_pseudo_pages(text.replace("\r\n", "\n"))


def extract(path, kind):
    return extract_pdf(path) if kind == "pdf" else extract_txt(path)
