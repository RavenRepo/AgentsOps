"""Second-pass extractor: turn findings into structured CLAIMS.

A finding is "what was observed" (one source said one thing).
A claim is "what we believe might be true" — a statement that may be supported
by ONE OR MORE findings, with a verification_status reflecting evidence quality.

This separation is the canonical research-agent pattern: a finding is not a
claim, a claim is not verified knowledge. Without this split, agents smuggle
uncertainty into confident prose.

Strategy:
- Group recent findings per topic.
- Ask the LLM to propose claim statements that synthesize 1..N findings into
  one believable statement.
- Tag each claim with verification_status driven by supporting-finding count
  and strength mix:
    verified    : ≥2 supporting findings AND all are strong/verified
    in-review   : ≥2 supporting findings, mixed strength
    unverified  : 1 supporting finding, or all supporting are weak
- Claims with status="unverified" become verification queue entries.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

# Path bootstrap so we can import the profile lib
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lib  # noqa: E402

CLAIM_PROMPT = """You are Goku's research-agent doing a SECOND PASS over recent findings.

Your job: synthesize findings into CLAIMS — believable statements that may be
supported by one or more findings. A claim is what you'd be willing to argue,
not just what one source said.

Rules:
- A claim should ABSTRACT across the supporting findings, not paraphrase a
  single one.
- Claims must be falsifiable and concrete. No vibes.
- It is fine to produce fewer claims than findings. Most findings won't
  cluster.
- DO NOT invent facts. If two findings disagree, surface a "disputed" claim
  rather than picking a side.
- Keep statements ≤ 240 characters.
- supporting_finding_ids must be EXACT ids from the input.

Output JSON ONLY with this exact shape:
{
  "claims": [
    {
      "statement": "<= 240 chars, falsifiable",
      "supporting_finding_ids": ["find-...", "find-..."],
      "topics": ["topic-slug"],
      "rationale": "1 short sentence on why these findings support the claim"
    }
  ]
}
"""


def _claim_id(statement: str) -> str:
    return "claim-" + hashlib.sha256(statement.encode("utf-8")).hexdigest()[:16]


def _verification_status(supporting: list[dict]) -> str:
    """Decide verification_status from the strength mix of supporting findings.

    verified  : >=2 supporting and ALL strength in {strong, verified}
    in-review : >=2 supporting, mixed strength
    unverified: 1 supporting, OR all supporting are weak
    """
    if not supporting:
        return "unverified"
    strengths = [s.get("strength", "weak") for s in supporting]
    n = len(supporting)
    all_strong = all(st in ("strong", "verified") for st in strengths)
    all_weak = all(st == "weak" for st in strengths)
    if n >= 2 and all_strong:
        return "verified"
    if n >= 2 and not all_weak:
        return "in-review"
    return "unverified"


def _verification_reason(supporting: list[dict]) -> str:
    """Reason a claim landed in the verification queue."""
    if len(supporting) <= 1:
        return "single-source"
    if all(s.get("strength") == "weak" for s in supporting):
        return "all-weak-evidence"
    return "needs-stronger-source"


def extract_claims(
    findings: list[dict],
    topics: list[str],
    model: str,
    *,
    max_findings_per_topic: int = 25,
    max_claims_per_topic: int = 10,
    timeout: int = 90,
    max_tokens: int = 1500,
) -> tuple[list[dict], list[dict]]:
    """Run the LLM claim builder over recent findings.

    Returns (claims, verification_queue_entries).

    A claim record looks like:
        {
          "claim_id": "claim-...",
          "statement": "...",
          "supporting_evidence": [evidence-ref, ...],
          "topics": ["..."],
          "verification_status": "verified|in-review|unverified",
          "rationale": "..."
        }

    A verification queue entry:
        {"claim_id": "...", "reason": "single-source|all-weak-evidence|...", "topic": "..."}
    """
    if not findings or not lib.is_provider_configured(model):
        return [], []

    # Bucket findings by topic
    by_topic: dict[str, list[dict]] = defaultdict(list)
    for f in findings:
        by_topic[f["topic"]].append(f)

    findings_by_id = {f["finding_id"]: f for f in findings}

    all_claims: list[dict] = []
    queue_entries: list[dict] = []

    for topic in topics:
        bucket = by_topic.get(topic, [])[:max_findings_per_topic]
        if len(bucket) < 2:
            # Single finding — emits one claim if strength allows, no LLM needed
            for f in bucket:
                stmt = f["summary"][:240]
                cid = _claim_id(stmt)
                supporting_evidence = [
                    {
                        "source_id": f["finding_id"],
                        "source_type": "finding",
                        "url": f["source"].get("url", ""),
                        "excerpt": f["summary"][:1500],
                        "captured_at": f["source"].get("captured_at"),
                    }
                ]
                claim = {
                    "claim_id": cid,
                    "statement": stmt,
                    "supporting_evidence": supporting_evidence,
                    "topics": [topic],
                    "verification_status": _verification_status([f]),
                    "rationale": "Single finding promoted as candidate claim.",
                }
                # Drop rationale before output (not in schema) — kept for ledger only
                ledger_claim = dict(claim)
                schema_claim = {k: v for k, v in claim.items() if k != "rationale"}
                all_claims.append({"_ledger": ledger_claim, "_schema": schema_claim})
                if claim["verification_status"] == "unverified":
                    queue_entries.append({
                        "claim_id": cid,
                        "reason": _verification_reason([f]),
                        "topic": topic,
                    })
            continue

        # Multi-finding topic — ask the model to cluster
        items_payload = [
            {
                "finding_id": f["finding_id"],
                "summary": f["summary"][:600],
                "strength": f.get("strength", "weak"),
                "url": f["source"].get("url", ""),
            }
            for f in bucket
        ]
        user = (
            f"Topic: {topic}\n"
            f"Findings (id + summary + strength + url):\n"
            f"{json.dumps(items_payload, indent=2)[:7000]}\n\n"
            f"Synthesize up to {max_claims_per_topic} claims. Cluster findings that "
            f"support the same statement. Skip findings that don't yield a real claim."
        )
        try:
            resp = lib.call_model(
                model=model,
                messages=[
                    {"role": "system", "content": CLAIM_PROMPT},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                max_tokens=max_tokens,
                json_mode=True,
                timeout=timeout,
            )
            decisions = json.loads(resp).get("claims", [])
        except (lib.LLMError, json.JSONDecodeError) as e:
            print(f"[claims] WARN: LLM failed for topic {topic}: {e}")
            continue

        seen_ids: set[str] = set()
        for d in decisions[:max_claims_per_topic]:
            stmt = (d.get("statement") or "").strip()
            if not stmt or len(stmt) > 240:
                continue
            sup_ids = d.get("supporting_finding_ids") or []
            supporting_findings = [
                findings_by_id[fid] for fid in sup_ids if fid in findings_by_id
            ]
            if not supporting_findings:
                continue

            cid = _claim_id(stmt)
            if cid in seen_ids:
                continue
            seen_ids.add(cid)

            supporting_evidence = [
                {
                    "source_id": f["finding_id"],
                    "source_type": "finding",
                    "url": f["source"].get("url", ""),
                    "excerpt": f["summary"][:1500],
                    "captured_at": f["source"].get("captured_at"),
                }
                for f in supporting_findings
            ]
            claim_topics = sorted(set([topic] + (d.get("topics") or [])))
            # Filter to known topics only (schema constraint)
            claim_topics = [t for t in claim_topics if t in topics]

            schema_claim = {
                "claim_id": cid,
                "statement": stmt,
                "supporting_evidence": supporting_evidence,
                "topics": claim_topics or [topic],
                "verification_status": _verification_status(supporting_findings),
            }
            ledger_claim = dict(schema_claim)
            ledger_claim["rationale"] = (d.get("rationale") or "")[:300]
            ledger_claim["produced_at"] = lib.now_iso()

            all_claims.append({"_ledger": ledger_claim, "_schema": schema_claim})

            if schema_claim["verification_status"] == "unverified":
                queue_entries.append({
                    "claim_id": cid,
                    "reason": _verification_reason(supporting_findings),
                    "topic": topic,
                })

    return all_claims, queue_entries
