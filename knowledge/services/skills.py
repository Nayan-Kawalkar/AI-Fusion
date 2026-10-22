"""Skills: SKILL.md instruction packs triggered with /name in Chat or the problem box.

File format (YAML front matter + markdown instructions):

    ---
    name: django-backend
    description: Django views, models and QuerySet questions
    docs: [django_querysets, "python_*"]        # KB title patterns to search
    urls:                                       # web docs fetched into the KB
      - https://docs.djangoproject.com/en/5.1/ref/models/querysets/
    ---
    Instructions the assistant follows while the skill is active.
"""
import fnmatch
import re

import yaml
from django.db import transaction

from ..models import Document, Skill

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,59}$")
TRIGGER_RE = re.compile(r"^\s*/([a-z0-9][a-z0-9-]*)(?:\s+|$)(.*)$", re.S)
FRONT_RE = re.compile(r"^﻿?---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)
MAX_URLS = 8
MAX_INSTRUCTIONS = 8000


class SkillError(Exception):
    pass


def parse_skill(text):
    """Validate a SKILL.md and return its fields."""
    m = FRONT_RE.match(text or "")
    if not m:
        raise SkillError("A skill file must start with a --- front-matter block (name, description, docs, urls).")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise SkillError(f"Front matter is not valid YAML: {e}") from e
    if not isinstance(meta, dict):
        raise SkillError("Front matter must be key: value pairs.")
    name = str(meta.get("name") or "").strip().lower()
    if not NAME_RE.match(name):
        raise SkillError("name must be 2-60 characters: lowercase letters, digits and dashes (e.g. frontend-ui).")

    def str_list(key):
        value = meta.get(key) or []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise SkillError(f"{key} must be a list.")
        return [str(v).strip() for v in value if str(v).strip()]

    urls = str_list("urls")
    for u in urls:
        if not re.match(r"^https?://", u):
            raise SkillError(f"URL must start with http:// or https://: {u}")
    if len(urls) > MAX_URLS:
        raise SkillError(f"At most {MAX_URLS} URLs per skill.")
    instructions = m.group(2).strip()
    if len(instructions) > MAX_INSTRUCTIONS:
        raise SkillError(f"Instructions are longer than {MAX_INSTRUCTIONS} characters.")
    return {
        "name": name,
        "description": str(meta.get("description") or "").strip()[:300],
        "docs": str_list("docs"),
        "urls": urls,
        "instructions": instructions,
    }


def install_skill(text, fetch=True):
    """Create or update a skill and fetch its URLs. Returns (skill, url_results)."""
    from .web import ingest_url

    fields = parse_skill(text)
    with transaction.atomic():
        skill, _ = Skill.objects.update_or_create(name=fields["name"], defaults={**fields, "source": text})
    results = []
    for url in skill.urls if fetch else []:
        try:
            doc, fetched = ingest_url(url)
            results.append({"url": url, "ok": True, "title": doc.title, "chunks": doc.chunks.count(), "fetched": fetched})
        except Exception as e:  # FetchError, IngestError, network: one bad URL shouldn't block the skill
            results.append({"url": url, "ok": False, "error": str(e)[:300]})
    return skill, results


def resolve_doc_ids(skill):
    """Knowledge-base documents this skill searches: title patterns + its fetched URLs.

    Returns None when the skill doesn't restrict docs (search everything).
    """
    if not skill.docs and not skill.urls:
        return None
    ids = set()
    if skill.docs:
        patterns = [p.lower() for p in skill.docs]
        for doc_id, title in Document.objects.values_list("id", "title"):
            t = title.lower()
            if any(fnmatch.fnmatch(t, p) or t == p for p in patterns):
                ids.add(doc_id)
    if skill.urls:
        ids.update(Document.objects.filter(source_url__in=skill.urls).values_list("id", flat=True))
    return sorted(ids)


def parse_trigger(text):
    """'/name rest' → (Skill, rest). No leading slash → (None, text). Unknown skill → SkillError."""
    m = TRIGGER_RE.match(text or "")
    if not m:
        return None, text
    skill = Skill.objects.filter(name=m.group(1)).first()
    if skill is None:
        names = ", ".join(f"/{n}" for n in Skill.objects.values_list("name", flat=True)) or "none installed"
        raise SkillError(f"Unknown skill /{m.group(1)}. Available: {names}.")
    return skill, m.group(2).strip()


def skill_info(skill):
    """What the UI shows for an active skill."""
    if skill is None:
        return None
    ids = resolve_doc_ids(skill)
    titles = list(Document.objects.filter(id__in=ids or []).values_list("title", flat=True))
    return {"name": skill.name, "description": skill.description, "docs": titles,
            "scoped": ids is not None, "urls": skill.urls}


def snapshot(skill):
    """The parts of a skill stored with a retrieval, so the answer uses exactly what was retrieved with."""
    if skill is None:
        return None
    return {"name": skill.name, "description": skill.description, "instructions": skill.instructions}


def prompt_block(snap):
    """Text injected into prompts while a skill is active (snap from snapshot())."""
    if not snap:
        return ""
    return (f"ACTIVE SKILL: /{snap['name']} — {snap['description']}\n"
            f"Follow these skill instructions (they refine, never override, the rules above):\n{snap['instructions']}")


def activate(text):
    """Parse a leading /skill. Returns (skill, rest, doc_ids, info) — doc_ids None means search all docs."""
    skill, rest = parse_trigger(text)
    if skill is None:
        return None, text, None, None
    return skill, rest, resolve_doc_ids(skill), skill_info(skill)
