"""
EIV — Reputation aggregation

Computes a trust profile for an agent address from its validation history.
The store provides the raw verdicts; this module adds scoring and analysis.

Trust score is a simple pass-rate percentage (0–100). Risk level thresholds:
  low    : score >= 80  (mostly compliant)
  medium : score >= 50  (mixed record)
  high   : score <  50  (frequent violations)
  unknown: no validation history

The category breakdown (A–G violation counts) shows where the agent tends
to violate, which is more actionable than the aggregate score alone.
"""

from __future__ import annotations

from typing import Optional


def compute_reputation(records: list[dict], agent_address: str) -> dict:
    """Compute a trust profile from a list of validation records."""
    if not records:
        return {
            "agent": agent_address,
            "trust_score": None,
            "risk_level": "unknown",
            "total_validations": 0,
            "pass_count": 0,
            "fail_count": 0,
            "pass_rate": None,
            "violations_by_category": {},
            "recent_verdicts": [],
        }

    pass_count = 0
    fail_count = 0
    category_counts: dict[str, int] = {}

    for rec in records:
        result = rec.get("result", {})
        verdict = result.get("verdict", "UNKNOWN")
        if verdict == "PASS":
            pass_count += 1
        elif verdict == "FAIL":
            fail_count += 1

        for v in result.get("violations", []):
            cat = v.get("category", "?")
            if v.get("severity") == "FAIL":
                category_counts[cat] = category_counts.get(cat, 0) + 1

    total = len(records)
    pass_rate = round(pass_count / total * 100, 1) if total > 0 else 0
    trust_score = round(pass_rate)

    if trust_score >= 80:
        risk_level = "low"
    elif trust_score >= 50:
        risk_level = "medium"
    else:
        risk_level = "high"

    by_time = sorted(records, key=lambda r: r.get("created_at", ""), reverse=True)
    recent = [
        {
            "validation_id": r.get("validation_id"),
            "verdict": r.get("result", {}).get("verdict"),
            "created_at": r.get("created_at"),
        }
        for r in by_time[:10]
    ]

    return {
        "agent": agent_address,
        "trust_score": trust_score,
        "risk_level": risk_level,
        "total_validations": total,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "pass_rate": pass_rate,
        "violations_by_category": dict(sorted(category_counts.items())),
        "recent_verdicts": recent,
    }
