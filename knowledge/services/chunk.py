"""Heading-aware document chunker that never splits a code block.

Input is [(page, text)]. Lines are grouped into heading / code / paragraph
blocks across page boundaries, then packed into ~TARGET-char chunks with a
~OVERLAP-char prose overlap. Code blocks (fenced ``` or runs of lines indented
4+ spaces / ">>>" prompts) are always kept whole, even if oversized.
"""
import re

TARGET = 2400
OVERLAP = 300

MD_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")
UNDERLINE = re.compile(r"^(=+|-+)\s*$")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _is_code_line(line):
    return line.startswith("    ") or line.startswith("\t") or line.lstrip().startswith(">>>")


def _is_caps_heading(line):
    s = line.strip()
    letters = [c for c in s if c.isalpha()]
    return 3 <= len(s) <= 60 and len(letters) >= 3 and s.upper() == s and s[-1] not in ".:;,!?"


def to_blocks(pages):
    """Group lines into [{kind, text, page}] blocks; kind is heading|code|para."""
    lines = [(page, line.rstrip()) for page, text in pages for line in text.split("\n")]
    blocks, i, n = [], 0, len(lines)
    while i < n:
        page, line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("```"):
            j = i + 1
            while j < n and not lines[j][1].strip().startswith("```"):
                j += 1
            j = min(j + 1, n)
            blocks.append({"kind": "code", "text": "\n".join(l for _, l in lines[i:j]), "page": page})
            i = j
            continue
        m = MD_HEADING.match(stripped)
        if m:
            blocks.append({"kind": "heading", "text": m.group(1).strip(), "page": page})
            i += 1
            continue
        if i + 1 < n and UNDERLINE.match(lines[i + 1][1].strip()) and len(stripped) < 100 and not _is_code_line(line):
            blocks.append({"kind": "heading", "text": stripped, "page": page})
            i += 2
            continue
        if _is_code_line(line):
            j = i
            last_code = i
            while j < n:
                l = lines[j][1]
                if _is_code_line(l):
                    last_code = j
                elif l.strip():
                    break
                j += 1
            blocks.append({"kind": "code", "text": "\n".join(l for _, l in lines[i : last_code + 1]), "page": page})
            i = last_code + 1
            continue
        if _is_caps_heading(line):
            blocks.append({"kind": "heading", "text": stripped.title(), "page": page})
            i += 1
            continue
        j = i
        para = []
        while j < n:
            l = lines[j][1]
            if (not l.strip() or _is_code_line(l) or l.strip().startswith("```")
                    or MD_HEADING.match(l.strip()) or (para and j + 1 < n and UNDERLINE.match(lines[j + 1][1].strip()))):
                break
            para.append(l)
            j += 1
        blocks.append({"kind": "para", "text": "\n".join(para), "page": page})
        i = j
    return blocks


def _split_long_para(block):
    """Split an oversized paragraph at sentence (then word) boundaries."""
    sentences = []
    for sent in SENTENCE_END.split(block["text"]):
        while len(sent) > TARGET:
            cut = sent.rfind(" ", 0, TARGET)
            cut = cut if cut > 0 else TARGET
            sentences.append(sent[:cut])
            sent = sent[cut:].lstrip()
        sentences.append(sent)
    pieces, cur = [], ""
    for sent in sentences:
        if cur and len(cur) + 1 + len(sent) > TARGET:
            pieces.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}" if cur else sent
    if cur:
        pieces.append(cur)
    return [{"kind": "para", "text": p, "page": block["page"]} for p in pieces]


def _overlap_tail(blocks):
    """Trailing prose (never code) of up to ~OVERLAP chars to seed the next chunk."""
    if not blocks or blocks[-1]["kind"] != "para":
        return []
    text = blocks[-1]["text"]
    if len(text) <= OVERLAP:
        tail = text
    else:
        tail = text[-OVERLAP:]
        boundary = SENTENCE_END.search(tail)
        tail = tail[boundary.end():] if boundary and boundary.end() < len(tail) else tail.split(" ", 1)[-1]
    return [{"kind": "overlap", "text": tail.strip(), "page": blocks[-1]["page"]}] if tail.strip() else []


def chunk_pages(pages):
    """Return [{text, page, heading}] chunks for [(page, text)] input."""
    chunks = []
    cur, cur_len, heading, section = [], 0, "", ""

    def has_content():
        return any(b["kind"] in ("para", "code") for b in cur)

    def emit(with_overlap):
        nonlocal cur, cur_len, heading
        if has_content():
            first = next(b for b in cur if b["kind"] != "overlap")
            text = "\n\n".join(("## " + b["text"]) if b["kind"] == "heading" else b["text"] for b in cur)
            chunks.append({"text": text.strip(), "page": first["page"], "heading": heading})
        tail = _overlap_tail(cur) if with_overlap else []
        cur, cur_len, heading = tail, sum(len(b["text"]) for b in tail), section

    for block in to_blocks(pages):
        if block["kind"] == "heading":
            if has_content():
                emit(with_overlap=False)
            elif cur and cur[-1]["kind"] == "overlap":
                cur, cur_len = [], 0
            section = heading = block["text"]
            cur.append(block)
            cur_len += len(block["text"])
            continue
        pieces = [block] if block["kind"] == "code" or len(block["text"]) <= TARGET else _split_long_para(block)
        for piece in pieces:
            if has_content() and cur_len + len(piece["text"]) > TARGET:
                emit(with_overlap=True)
            cur.append(piece)
            cur_len += len(piece["text"]) + 2
    emit(with_overlap=False)
    return chunks
