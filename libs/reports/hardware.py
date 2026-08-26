"""Hardware reliability stats from Paddles runs, jobs, and node inventory.

Architecture comes from Paddles ``/nodes/`` (majority ``arch`` per
``machine_type``). Unmapped types stay ``Unknown``. Paddles
``/jobs/?machine_type=`` does not honour that filter, so callers load a
posted window from the catalog, pick a machine type, then scope jobs in
memory.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from libs.exceptions import PaddlesAPIError
from libs.reports import DataSource
from libs.reports.jobs import JobsStats
from libs.reports.models import Job, TestRun
from libs.reports.parsing import as_node_list
from libs.reports.testruns import TestRunsStats

# Lab / provisioning failures — not product test assertion failures.
MACHINE_ERROR_RE = re.compile(
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


def _mt_key(value: str | None) -> str:
    return (value or "").strip().lower()


def build_arch_map_from_nodes(nodes: list[dict]) -> dict[str, str]:
    """Build ``machine_type → arch`` from Paddles node inventory.

    Uses the majority ``arch`` value per machine_type.
    """
    votes: dict[str, Counter[str]] = {}
    for node in nodes or []:
        mt = _mt_key(node.get("machine_type"))
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
    mt = _mt_key(machine_type)
    if not mt:
        return "Unknown"
    return (arch_by_machine_type or {}).get(mt, "Unknown")


def is_machine_error(
    status: str | None,
    failure_reason: str | None = None,
    *,
    pattern: re.Pattern | None = None,
) -> bool:
    """Return True for lab/machine infrastructure failures.

    Rules
    -----
    - ``dead`` with a known machine-error reason → True
    - ``dead`` with NO reason (genuinely unknown) → True (infra-side assumption)
    - ``dead`` with a reason that does NOT match → False
      (test-side timeout kill, not a lab failure)
    - ``fail`` with a matching reason → True
    - ``fail`` with no or non-matching reason → False
    """
    regex = pattern or MACHINE_ERROR_RE
    s = (status or "").strip().lower()
    reason = (failure_reason or "").strip()

    if s == "dead":
        if not reason:
            return True
        return bool(regex.search(reason))

    if s == "fail":
        if not reason:
            return False
        return bool(regex.search(reason))

    return False


@dataclass
class HardwareStats:
    """Machine-type-centric view over already-loaded runs and jobs."""

    runs: TestRunsStats
    jobs: JobsStats
    arch_by_machine_type: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_testruns_jobs(
        cls,
        testruns: list[TestRun] | TestRunsStats,
        jobs: list[Job] | JobsStats,
        *,
        arch_by_machine_type: dict[str, str] | None = None,
    ) -> HardwareStats:
        run_stats = (
            testruns
            if isinstance(testruns, TestRunsStats)
            else TestRunsStats.from_testruns(testruns)
        )
        job_stats = (
            jobs if isinstance(jobs, JobsStats) else JobsStats.from_jobs(jobs)
        )
        return cls(
            runs=run_stats,
            jobs=job_stats,
            arch_by_machine_type=arch_by_machine_type or {},
        )

    @classmethod
    def load_arch_map(cls) -> dict[str, str]:
        """Return ``machine_type → arch`` from live Paddles ``/nodes/``."""
        try:
            client = DataSource()
            raw = client.node() if hasattr(client, "node") else []
        except PaddlesAPIError:
            return {}
        return build_arch_map_from_nodes(as_node_list(raw))

    def machine_types(self) -> list[str]:
        """Distinct machine types present on loaded testruns."""
        return sorted(
            {
                (run.machine_type or "").strip()
                for run in self.runs.testruns
                if (run.machine_type or "").strip()
            }
        )

    def architecture(self, machine_type: str | None = None) -> str:
        """Architecture label for ``machine_type`` (or the only loaded type)."""
        if machine_type:
            return classify_machine_type(machine_type, self.arch_by_machine_type)
        types = self.machine_types()
        if len(types) == 1:
            return classify_machine_type(types[0], self.arch_by_machine_type)
        return "Unknown"

    def for_machine_type(self, machine_type: str) -> HardwareStats:
        """Restrict to one lab class.

        Runs are matched on ``machine_type``. Jobs on those runs are kept
        unless they record a different machine type (mixed-lab runs).
        """
        wanted = _mt_key(machine_type)
        runs = self.runs.for_machine_type(machine_type)
        jobs = self.jobs.for_run_set(runs.testruns)
        if wanted:
            jobs = JobsStats.from_jobs(
                [
                    job
                    for job in jobs.jobs
                    if not _mt_key(job.machine_type)
                    or _mt_key(job.machine_type) == wanted
                ]
            )
        return HardwareStats(
            runs=runs,
            jobs=jobs,
            arch_by_machine_type=self.arch_by_machine_type,
        )
