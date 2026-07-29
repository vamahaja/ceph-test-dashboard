"""
libs/hardware.py
================
Classify jobs using live Paddles data only.

Architecture comes from Paddles ``/nodes/`` inventory (``arch`` per
``machine_type``). No static maps — unmapped types stay ``Unknown``.
"""

from __future__ import annotations

import re
from collections import Counter

# Lab / provisioning failures — not product test assertion failures.
# Exposed at module level so callers can use it for vectorised str.contains().
_MACHINE_ERROR_RE = re.compile(
    r"("
    r"reimaging\s+machines|"
    r"hit\s+max\s+job\s+timeout|"
    r"reached\s+maximum\s+tries|"
    r"unable\s+to\s+lock|"
    r"lock\s+failed|"
    r"could\s+not\s+lock|"
    r"no\s+free\s+(?:machines?|nodes?)|"
    r"ssh(?:\s|$|:)|"
    r"connection\s+(?:refused|reset|timed\s*out)|"
    r"timed\s+out\s+waiting\s+for\s+(?:machine|node|host)|"
    r"ansible|"
    r"power\s*-?\s*cycle|"
    r"failed\s+to\s+(?:power|provision|reimage)|"
    r"libvirt|"
    r"ipmi|"
    r"console\s+is\s+dead"
    r")",
    re.IGNORECASE,
)


def build_arch_map_from_nodes(nodes: list[dict]) -> dict[str, str]:
    """
    Build ``machine_type → arch`` from Paddles node inventory.

    Uses the majority ``arch`` value per machine_type.
    """
    votes: dict[str, Counter[str]] = {}
    for node in nodes or []:
        mt = (node.get("machine_type") or "").strip().lower()
        arch = (node.get("arch") or "").strip()
        if not mt or not arch:
            continue
        votes.setdefault(mt, Counter())[arch] += 1

    return {
        mt: counter.most_common(1)[0][0]
        for mt, counter in votes.items()
        if counter
    }


def classify_machine_type(
    machine_type: str | None,
    arch_by_machine_type: dict[str, str] | None = None,
) -> str:
    """Return architecture for a machine_type from the live nodes map."""
    if not machine_type or not str(machine_type).strip():
        return "Unknown"

    mt = str(machine_type).strip().lower()
    arch_map = arch_by_machine_type or {}
    return arch_map.get(mt, "Unknown")


def enrich_jobs_with_hardware(
    jobs: list[dict],
    arch_by_machine_type: dict[str, str] | None = None,
) -> list[dict]:
    """
    Add ``architecture`` from the live nodes map to each job dict.

    Kept for backwards compatibility. For DataFrame-based callers prefer
    the vectorised helper ``enrich_dataframe_with_hardware`` instead.
    """
    arch_map = arch_by_machine_type or {}
    enriched = []
    for job in jobs:
        row = dict(job)
        mt = (job.get("machine_type") or "").strip().lower()
        row["architecture"] = arch_map.get(mt, "Unknown")
        enriched.append(row)
    return enriched


def enrich_dataframe_with_hardware(
    df: "pd.DataFrame",
    arch_by_machine_type: dict[str, str] | None = None,
    fallback_arch: str = "Unknown",
) -> "pd.DataFrame":
    """
    Vectorised version of ``enrich_jobs_with_hardware`` for pandas DataFrames.

    Adds an ``architecture`` column using a vectorised ``Series.map`` call
    instead of a Python row loop. Caller must have already created the
    DataFrame before calling this function.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain a ``machine_type`` column.
    arch_by_machine_type : dict
        ``machine_type (lowercase) → arch`` mapping from live Paddles nodes.
    fallback_arch : str
        Value used when a machine_type is absent from the map.
    """
    arch_map = arch_by_machine_type or {}
    df = df.copy()
    df["architecture"] = (
        df["machine_type"]
        .str.strip()
        .str.lower()
        .map(arch_map)
        .fillna(fallback_arch)
    )
    return df


def is_machine_error(
    status: str | None,
    failure_reason: str | None = None,
) -> bool:
    """
    Return True for lab/machine infrastructure failures.

    Rules
    -----
    - ``dead`` with a known machine-error reason → True
    - ``dead`` with NO reason (genuinely unknown) → True (infra-side assumption)
    - ``dead`` with a reason that does NOT match → False
      (test-side timeout kill, not a lab failure)
    - ``fail`` with a matching reason → True
    - ``fail`` with no or non-matching reason → False
    """
    s = (status or "").strip().lower()
    reason = (failure_reason or "").strip()

    if s == "dead":
        # No reason recorded → assume infra (genuine machine death)
        if not reason:
            return True
        # Reason matches a known machine-error pattern → lab failure
        if bool(_MACHINE_ERROR_RE.search(reason)):
            return True
        # Dead with a non-matching reason → likely test-timeout kill, not lab
        return False

    # For "fail" status, require a positive reason match
    if not reason:
        return False
    return bool(_MACHINE_ERROR_RE.search(reason))
