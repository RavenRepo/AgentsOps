#!/usr/bin/env python3
"""
studio.py — content-studio entry point.

Modes:
  seed --topic "<one-liner>" [--platforms medium,x,linkedin,substack] [--slug <slug>]
       Create a manual seed + content-track manifest. Returns slug.

  draft --slug <slug> [--platform <p>]
       Generate platform draft(s) for a track. If --platform omitted, drafts ALL
       platforms named in the track manifest.

  humanize --slug <slug> [--platform <p>]
       Apply humanizer pass to drafts. Idempotent on already-humanized drafts.

  editor-review --slug <slug>
       Score all platform drafts in the track, pick a winner, write editor-review.json.

Hard rules (also in SOUL.md):
  - Drafts MUST cite which playbook tactics they apply.
  - editor-review CANNOT select a draft with humanized: false.
  - Every artifact validates before being written.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))

import lib  # noqa: E402

SEED_FILENAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,127}$")


def _slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len] or "untitled"


def _load_voice() -> str:
    if not lib.VOICE_MD.exists():
        return ""
    return lib.VOICE_MD.read_text()


def _voice_has_real_samples(voice: str) -> bool:
    """Heuristic: voice.md is "real" if it has populated sample blocks."""
    populated = 0
    for line in voice.splitlines():
        line = line.strip()
        if line.startswith("### Sample") and "(paste here)" not in line:
            populated += 1
    return populated >= 1


def _load_playbook(platform: str) -> str:
    p = lib.playbook_md(platform)
    return p.read_text() if p.exists() else "(no playbook yet)"


def _load_recent_findings(platform: str, n: int = 8) -> list[dict]:
    fp = lib.platform_vault(platform) / "findings.jsonl"
    if not fp.exists():
        return []
    out = list(lib.read_jsonl(fp))
    return out[-n:]


# ---------------------------------------------------------------------------
# seed mode
# ---------------------------------------------------------------------------

def mode_seed(args, config: dict) -> dict:
    if not args.topic:
        return {"mode": "seed", "result": "fail", "reason": "--topic required"}
    slug = args.slug or _slugify(args.topic)
    if not SEED_FILENAME_RE.match(slug):
        return {"mode": "seed", "result": "fail", "reason": f"bad slug: {slug}"}

    platforms = (args.platforms.split(",") if args.platforms else list(lib.PLATFORMS))
    platforms = [p.strip() for p in platforms if p.strip() in lib.PLATFORMS]
    if not platforms:
        return {"mode": "seed", "result": "fail", "reason": "no valid platforms"}

    lib.ensure_dirs()
    seed_path = lib.SEEDS_DIR / f"{slug}.json"
    seed = {
        "slug": slug,
        "topic": args.topic,
        "intent": args.intent or "",
        "platforms": platforms,
        "tags": [t.strip() for t in (args.tags or "").split(",") if t.strip()],
        "created_at": lib.now_iso(),
    }
    lib.write_json_atomic(seed_path, seed)

    manifest = {
        "schema_version": 1,
        "track_id": slug,
        "produced_by": "content-studio",
        "produced_at": lib.now_iso(),
        "topic": args.topic,
        "intent": args.intent or "",
        "platforms": platforms,
        "seed_source": "manual",
        "seed_ref": str(seed_path),
        "voice_baseline": str(lib.VOICE_MD),
        "tags": seed["tags"],
        "status": "seeded",
    }
    errs = lib.validate(manifest, "content-track")
    if errs:
        return {"mode": "seed", "result": "fail", "errors": errs[:5]}
    lib.write_json_atomic(lib.track_manifest(slug), manifest)

    return {"mode": "seed", "result": "ok", "slug": slug,
            "platforms": platforms,
            "wrote": [str(seed_path), str(lib.track_manifest(slug))]}


# ---------------------------------------------------------------------------
# draft mode
# ---------------------------------------------------------------------------

DRAFT_PROMPT_TMPL = """You are a professional ghostwriter drafting a {platform} post for the user.

Their voice (mimic it — phrases, cadence, stance, what they avoid):
---
{voice}
---

The platform's playbook (apply at least 2 tactics; cite them in your output meta):
---
{playbook}
---

Recent findings the agent has observed about this platform (pick from these if useful):
---
{findings}
---

Topic seed:
---
TOPIC: {topic}
INTENT: {intent}
TAGS: {tags}
---

Output a JSON object with this exact shape:
{{
  "title": "<title or null>",
  "hook": "<first 1-3 lines>",
  "body_markdown": "<the full draft in markdown>",
  "applied_tactics": ["tactic name 1", "tactic name 2", ...]
}}
Do not wrap in code fences. Be specific. Do not pad. If the topic is thin, write less.
"""


def _draft_one(slug: str, platform: str, manifest: dict, voice: str,
               playbook: str, findings: list[dict], config: dict) -> dict:
    # Hard rule: X uses its own dedicated model (nemotron-mini-4b free, or grok when funded).
    # All other platforms use the standard drafter.
    if platform == "x":
        model = config["models"].get("x_drafter") or config["models"]["drafter"]
    else:
        model = config["models"]["drafter"]
    if not lib.is_provider_configured(model):
        return {"platform": platform, "result": "skipped",
                "reason": f"provider not configured for {model}"}

    user = DRAFT_PROMPT_TMPL.format(
        platform=platform,
        voice=voice[:6000] if voice else "(no voice samples — write neutral, declarative, first-person)",
        playbook=playbook[:3000],
        findings=json.dumps(findings, indent=2)[:3000] if findings else "(no findings yet)",
        topic=manifest.get("topic", ""),
        intent=manifest.get("intent", ""),
        tags=", ".join(manifest.get("tags", [])),
    )
    try:
        resp = lib.call_model(
            model=model,
            messages=[
                {"role": "system", "content": f"You write platform-native {platform} drafts. Strict JSON output."},
                {"role": "user", "content": user},
            ],
            temperature=0.5,
            max_tokens=4000,
            json_mode=True,
            timeout=180,
        )
        data = json.loads(resp)
    except (lib.LLMError, json.JSONDecodeError) as e:
        return {"platform": platform, "result": "fail", "reason": str(e)}

    body = (data.get("body_markdown") or "").strip()
    if not body:
        return {"platform": platform, "result": "fail", "reason": "empty draft body"}

    md_path = lib.draft_md(slug, platform)
    meta_path = lib.draft_meta(slug, platform)
    lib.write_atomic(md_path, body + "\n")

    draft_id = f"draft-{slug}-{platform}-{lib.now_run_id()}"
    meta = {
        "schema_version": 1,
        "draft_id": draft_id,
        "track_id": slug,
        "platform": platform,
        "produced_by": "content-studio",
        "produced_at": lib.now_iso(),
        "model": model,
        "draft_path": md_path.name,
        "title": data.get("title") or "",
        "hook": data.get("hook") or "",
        "word_count": len(body.split()),
        "humanized": False,
        "humanizer_voice_path": str(lib.VOICE_MD),
        "applied_tactics": (data.get("applied_tactics") or [])[:20],
    }
    errs = lib.validate(meta, "content-draft")
    if errs:
        return {"platform": platform, "result": "fail", "errors": errs[:5]}
    lib.write_json_atomic(meta_path, meta)
    return {"platform": platform, "result": "ok",
            "draft_id": draft_id,
            "word_count": meta["word_count"],
            "applied_tactics": meta["applied_tactics"]}


def mode_draft(args, config: dict) -> dict:
    if not args.slug:
        return {"mode": "draft", "result": "fail", "reason": "--slug required"}
    manifest_path = lib.track_manifest(args.slug)
    if not manifest_path.exists():
        return {"mode": "draft", "result": "fail",
                "reason": f"track manifest not found at {manifest_path}"}
    manifest = json.loads(manifest_path.read_text())

    targets = ([args.platform] if args.platform else list(manifest.get("platforms", lib.PLATFORMS)))
    targets = [p for p in targets if p in lib.PLATFORMS]
    voice = _load_voice()

    results = []
    for platform in targets:
        playbook = _load_playbook(platform)
        findings = _load_recent_findings(platform)
        results.append(_draft_one(args.slug, platform, manifest, voice, playbook, findings, config))

    # Update track status
    manifest["status"] = "drafting"
    manifest["produced_at"] = lib.now_iso()
    lib.write_json_atomic(manifest_path, manifest)

    return {"mode": "draft", "result": "ok", "slug": args.slug,
            "voice_has_real_samples": _voice_has_real_samples(voice),
            "platforms": targets, "results": results}


# ---------------------------------------------------------------------------
# humanize mode
# ---------------------------------------------------------------------------

HUMANIZE_PROMPT = """You are rewriting a draft to match the user's voice and remove AI writing patterns. Keep the substance.
Change the cadence, phrasing, vocabulary, structure — but don't add new claims.

TARGET PLATFORM: **{platform}**

CRITICAL: voice.md has per-platform register sections. **Use the {platform} register specifically.**
- Do NOT collapse a LinkedIn draft into X register, or vice versa.
- LinkedIn allows: title-case, em-dashes, bold-stylized headers, question CTAs, hashtag tail with 6-9 hashtags, bullet structure.
- X uses: lower-case starts, numerals not words, no em-dashes, no hashtag tail, no engagement-bait CTAs, period-separated micro-sentences, ">>" emphasis.
- Substack/Medium uses: long-form prose, bold-stylized numerals (𝟭/, 𝟮/), Phase N → VERB headers, code blocks, sharp question CTA at the end, italic subscribe pitch.

Match the platform's register. Keep the platform's conventions (hashtags on LinkedIn, no hashtags on X, etc.) intact in the rewrite.

{skill_block}

Voice samples (your reference for cadence and stance — pay attention to which platform each sample is FROM):
---
{voice}
---

Original draft (for {platform}):
---
{draft}
---

Output ONLY the rewritten markdown. No preface, no explanation, no code fences."""


# Path to the avoid-ai-writing skill (single canonical location)
AVOID_AI_SKILL_MD = Path("os.environ.get("GOKU_DATA_DIR", "/opt/agent-data")/skills/avoid-ai-writing/SKILL.md")


def _load_avoid_ai_skill() -> str:
    """Load the avoid-ai-writing skill rules. Returns empty string if not installed."""
    if not AVOID_AI_SKILL_MD.exists():
        return ""
    try:
        content = AVOID_AI_SKILL_MD.read_text()
        return (
            "AVOID-AI-WRITING SKILL (v3.4) — apply these rules during the rewrite:\n"
            "---\n" + content[:20000] + "\n---\n"
        )
    except OSError:
        return ""


def _humanize_one(slug: str, platform: str, voice: str, config: dict) -> dict:
    md_path = lib.draft_md(slug, platform)
    meta_path = lib.draft_meta(slug, platform)
    if not md_path.exists() or not meta_path.exists():
        return {"platform": platform, "result": "skipped", "reason": "no draft"}
    meta = json.loads(meta_path.read_text())
    if meta.get("humanized"):
        return {"platform": platform, "result": "skipped", "reason": "already humanized"}

    model = config["models"]["humanizer"]
    if not lib.is_provider_configured(model):
        return {"platform": platform, "result": "skipped",
                "reason": f"provider not configured for {model}"}

    skill_block = _load_avoid_ai_skill()
    has_voice = bool(voice and _voice_has_real_samples(voice))
    has_skill = bool(skill_block)

    # Without BOTH voice samples AND a skill, there's nothing meaningful to humanize against.
    # In that case, mark humanized=true with an honest note and move on.
    if not has_voice and not has_skill:
        meta["humanized"] = True
        meta["produced_at"] = lib.now_iso()
        meta["model"] = model
        meta["notes"] = (meta.get("notes") or "") + (
            "\n[humanizer no-op: voice.md has no samples AND avoid-ai-writing skill not installed]"
        )
        meta["notes"] = meta["notes"][:2000]
        errs = lib.validate(meta, "content-draft")
        if errs:
            return {"platform": platform, "result": "fail", "errors": errs[:5]}
        lib.write_json_atomic(meta_path, meta)
        return {"platform": platform, "result": "ok-noop",
                "reason": "no voice samples and no skill installed"}

    # Build the prompt using whatever we have
    voice_for_prompt = voice if has_voice else (
        "(voice.md has no real samples yet — rely on the avoid-ai-writing skill above. "
        "Default to first-person, declarative, specific numbers, no hedging.)"
    )

    draft_body = md_path.read_text()
    try:
        resp = lib.call_model(
            model=model,
            messages=[
                {"role": "system", "content": "You rewrite drafts to remove AI writing patterns and match a voice. Output markdown only."},
                {"role": "user", "content": HUMANIZE_PROMPT.format(
                    platform=platform,
                    skill_block=skill_block or "(avoid-ai-writing skill not installed; rely on voice samples only)",
                    voice=voice_for_prompt[:12000],
                    draft=draft_body[:8000],
                )},
            ],
            temperature=0.5,
            max_tokens=4000,
            timeout=180,
        )
    except lib.LLMError as e:
        return {"platform": platform, "result": "fail", "reason": str(e)}

    rewritten = resp.strip()
    if not rewritten:
        return {"platform": platform, "result": "fail", "reason": "empty rewrite"}

    lib.write_atomic(md_path, rewritten + "\n")
    meta["humanized"] = True
    meta["word_count"] = len(rewritten.split())
    meta["produced_at"] = lib.now_iso()
    meta["model"] = model
    notes = []
    if has_skill:
        notes.append("avoid-ai-writing v3.4 applied")
    if not has_voice:
        notes.append("voice.md empty — skill rules only")
    if notes:
        meta["notes"] = (meta.get("notes") or "") + "\n[" + "; ".join(notes) + "]"
        meta["notes"] = meta["notes"][:2000]
    errs = lib.validate(meta, "content-draft")
    if errs:
        return {"platform": platform, "result": "fail", "errors": errs[:5]}
    lib.write_json_atomic(meta_path, meta)
    return {"platform": platform, "result": "ok",
            "word_count": meta["word_count"],
            "skill_applied": has_skill,
            "voice_samples_used": has_voice}


def mode_humanize(args, config: dict) -> dict:
    if not args.slug:
        return {"mode": "humanize", "result": "fail", "reason": "--slug required"}
    voice = _load_voice()
    targets = ([args.platform] if args.platform else list(lib.PLATFORMS))
    results = [_humanize_one(args.slug, p, voice, config) for p in targets]
    return {"mode": "humanize", "result": "ok", "slug": args.slug,
            "voice_has_real_samples": _voice_has_real_samples(voice),
            "results": results}


# ---------------------------------------------------------------------------
# editor-review mode
# ---------------------------------------------------------------------------

EDITOR_PROMPT = """You are the editor reviewing platform drafts in a content track. The track has drafts for one or more platforms. Pick the BEST variant and rate the slate.

Track topic: {topic}
Track intent: {intent}

Drafts (only humanized=true drafts are eligible to win):
{drafts}

Output JSON ONLY with this exact shape:
{{
  "verdict": "ready" | "needs_revision" | "kill",
  "selected_draft_id": "<draft_id of winner, or null>",
  "scores": {{
    "voice_match": <0-10>,
    "algo_fit": <0-10>,
    "originality": <0-10>,
    "evidence_quality": <0-10>,
    "hook_strength": <0-10>
  }},
  "concerns": [{{"concern": "...", "severity": "info|minor|major|blocking"}}],
  "rationale": "<2-4 sentences on why this verdict>"
}}

Rules:
- A draft with humanized=false CANNOT be selected.
- Score honestly. Average drafts get 5s. A draft worth shipping reads as a 7+.
- If the voice samples are weak (you can tell from voice_match score), say so in rationale.
"""


def mode_editor_review(args, config: dict) -> dict:
    if not args.slug:
        return {"mode": "editor-review", "result": "fail", "reason": "--slug required"}
    manifest_path = lib.track_manifest(args.slug)
    if not manifest_path.exists():
        return {"mode": "editor-review", "result": "fail",
                "reason": "track manifest not found"}
    manifest = json.loads(manifest_path.read_text())
    drafts: list[dict] = []
    for p in manifest.get("platforms", lib.PLATFORMS):
        meta_path = lib.draft_meta(args.slug, p)
        md_path = lib.draft_md(args.slug, p)
        if not meta_path.exists() or not md_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        meta["_excerpt"] = md_path.read_text()[:2000]
        drafts.append(meta)
    if not drafts:
        return {"mode": "editor-review", "result": "fail", "reason": "no drafts found"}

    eligible = [d for d in drafts if d.get("humanized")]
    if not eligible:
        return {"mode": "editor-review", "result": "fail",
                "reason": "no humanized drafts (run humanize first)"}

    model = config["models"]["editor"]
    if not lib.is_provider_configured(model):
        return {"mode": "editor-review", "result": "skipped",
                "reason": f"provider not configured for {model}"}

    drafts_blob = json.dumps(
        [
            {
                "draft_id": d["draft_id"],
                "platform": d["platform"],
                "title": d.get("title", ""),
                "hook": d.get("hook", ""),
                "applied_tactics": d.get("applied_tactics", []),
                "humanized": d.get("humanized", False),
                "word_count": d.get("word_count", 0),
                "excerpt": d["_excerpt"],
            }
            for d in drafts
        ],
        indent=2,
    )[:12000]

    user = EDITOR_PROMPT.format(
        topic=manifest.get("topic", ""),
        intent=manifest.get("intent", ""),
        drafts=drafts_blob,
    )
    try:
        resp = lib.call_model(
            model=model,
            messages=[
                {"role": "system", "content": "You are the content editor. Strict JSON output."},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            max_tokens=2000,
            json_mode=True,
            timeout=180,
        )
        data = json.loads(resp)
    except (lib.LLMError, json.JSONDecodeError) as e:
        return {"mode": "editor-review", "result": "fail", "reason": str(e)}

    selected = data.get("selected_draft_id")
    eligible_ids = {d["draft_id"] for d in eligible}
    if selected and selected not in eligible_ids:
        # Editor picked a non-eligible draft; force kill
        data["verdict"] = "kill"
        data["selected_draft_id"] = None
        data.setdefault("concerns", []).append(
            {"concern": "Editor picked a draft that wasn't eligible (humanized=false). Forced kill.",
             "severity": "blocking"}
        )

    review = {
        "schema_version": 1,
        "review_id": f"review-{args.slug}-{lib.now_run_id()}",
        "track_id": args.slug,
        "platform": eligible[0]["platform"] if data.get("selected_draft_id") is None
                    else next((d["platform"] for d in drafts if d["draft_id"] == data["selected_draft_id"]), eligible[0]["platform"]),
        "produced_by": "content-studio",
        "produced_at": lib.now_iso(),
        "model": model,
        "verdict": data.get("verdict") or "needs_revision",
        "selected_draft_id": data.get("selected_draft_id"),
        "scores": data.get("scores") or {},
        "concerns": data.get("concerns") or [],
        "rationale": (data.get("rationale") or "")[:4000],
    }
    # Strip selected_draft_id if null (schema allows missing rather than null)
    if review["selected_draft_id"] is None:
        review.pop("selected_draft_id")
    errs = lib.validate(review, "editor-review")
    if errs:
        return {"mode": "editor-review", "result": "fail", "errors": errs[:5]}
    lib.write_json_atomic(lib.editor_review_path(args.slug), review)

    # Update track status
    manifest["status"] = "ready" if review["verdict"] == "ready" else "editing"
    manifest["produced_at"] = lib.now_iso()
    lib.write_json_atomic(manifest_path, manifest)

    return {"mode": "editor-review", "result": "ok", "slug": args.slug,
            "verdict": review["verdict"],
            "selected_draft_id": review.get("selected_draft_id"),
            "scores": review.get("scores", {})}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)

    s = sub.add_parser("seed")
    s.add_argument("--topic", required=True)
    s.add_argument("--intent", default="")
    s.add_argument("--platforms")
    s.add_argument("--tags")
    s.add_argument("--slug")

    d = sub.add_parser("draft")
    d.add_argument("--slug", required=True)
    d.add_argument("--platform")

    h = sub.add_parser("humanize")
    h.add_argument("--slug", required=True)
    h.add_argument("--platform")

    e = sub.add_parser("editor-review")
    e.add_argument("--slug", required=True)

    args = ap.parse_args()
    config = lib.load_profile_config(lib.PROFILE_ROOT)
    lib.ensure_dirs()

    handlers = {
        "seed":          lambda: mode_seed(args, config),
        "draft":         lambda: mode_draft(args, config),
        "humanize":      lambda: mode_humanize(args, config),
        "editor-review": lambda: mode_editor_review(args, config),
    }
    receipt = handlers[args.mode]()
    print(json.dumps(receipt, indent=2))
    return 0 if receipt.get("result") in {"ok", "ok-noop", "skipped"} else 1


if __name__ == "__main__":
    sys.exit(main())
