#!/usr/bin/env python3
"""Model Context Protocol (MCP) server for the Paddles API.

Exposes tools to fetch test runs, jobs, and node details from the Paddles API
used by the Ceph Teuthology test dashboard.
"""

import sys
import os
from pathlib import Path

# Remove the current script's directory from sys.path to prevent shadowing
# the 'mcp' library.
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path = [p for p in sys.path if os.path.abspath(p) != script_dir]

# Add project root to sys.path to allow importing libs modules
# from subdirectories.
project_root = str(Path(__file__).resolve().parents[2])
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp.server import MCPServer
from libs.paddle import Paddles
from libs.exceptions import ConfigError
from libs.reports.testruns import TestRunsStats
from libs.reports.jobs import JobsStats
from libs.reports.hardware import HardwareStats

# Initialize MCPServer
mcp = MCPServer("Paddles API Server")

# Lazy Paddles client initialization to avoid crashing on import if config
# is missing.
_paddles = None


def get_paddles_client() -> Paddles:
    """Lazily initialize and return the Paddles client instance."""
    global _paddles
    if _paddles is None:
        try:
            _paddles = Paddles()
        except ConfigError as e:
            raise RuntimeError(
                f"Configuration Error: {e}. Please configure the dashboard "
                "INI file or set the CEPH_TEST_DASHBOARD_CONFIG environment "
                "variable."
            ) from e
        except FileNotFoundError as e:
            raise RuntimeError(
                f"Configuration File Not Found: {e}. Please copy the config "
                "template to ~/.config/ceph-test-dashboard.ini and edit it."
            ) from e
    return _paddles


@mcp.tool()
def get_runs(
    run_name: str | None = None,
    branch: str | None = None,
    suite: str | None = None,
    status: str | None = None,
    user: str | None = None,
    date: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    count: int = 0,
    page: int = 0,
) -> str | dict | list:
    """Fetch runs from the Paddles API.

    Supports querying a single run by name or listing runs with various
    filters.

    Args:
        run_name: Name of a specific run to fetch. If specified, other
          filters are ignored.
        branch: Filter runs by branch name (e.g., 'main', 'squid').
        suite: Filter runs by suite name.
        status: Filter runs by status (e.g., 'pass', 'fail', 'dead').
        user: Filter runs by scheduling user.
        date: Filter runs by scheduled date (YYYY-MM-DD).
        date_start: Start date for date range filter (YYYY-MM-DD).
        date_end: End date for date range filter (YYYY-MM-DD).
        count: Number of runs to return (for pagination).
        page: Page number to fetch (for pagination).
    """
    try:
        client = get_paddles_client()
        return client.run(
            run_name=run_name,
            branch=branch,
            suite=suite,
            status=status,
            user=user,
            date=date,
            date_start=date_start,
            date_end=date_end,
            count=count,
            page=page,
        )
    except Exception as e:
        return f"Error fetching runs: {e}"


@mcp.tool()
def get_jobs_for_run(run_name: str) -> str | list:
    """Fetch all jobs associated with a specific run name.

    Args:
        run_name: The name of the run to fetch jobs for.
    """
    try:
        client = get_paddles_client()
        return client.jobs_for_run(run_name)
    except Exception as e:
        return f"Error fetching jobs for run '{run_name}': {e}"


@mcp.tool()
def get_jobs(
    status: str | None = None,
    branch: str | None = None,
    suite: str | None = None,
    sha1: str | None = None,
    os_type: str | None = None,
    user: str | None = None,
    machine_type: str | None = None,
    count: int = 0,
    page: int = 0,
) -> str | list:
    """Fetch jobs from the Paddles API with optional filtering.

    Args:
        status: Filter jobs by status (e.g., 'pass', 'fail', 'dead').
        branch: Filter jobs by branch name.
        suite: Filter jobs by suite name.
        sha1: Filter jobs by commit SHA1.
        os_type: Filter jobs by OS type (e.g., 'ubuntu', 'centos').
        user: Filter jobs by user.
        machine_type: Filter jobs by machine type.
        count: Number of jobs to return (for pagination).
        page: Page number to fetch (for pagination).
    """
    try:
        client = get_paddles_client()
        return client.jobs(
            status=status,
            branch=branch,
            suite=suite,
            sha1=sha1,
            os_type=os_type,
            user=user,
            machine_type=machine_type,
            count=count,
            page=page,
        )
    except Exception as e:
        return f"Error fetching jobs: {e}"


@mcp.tool()
def get_nodes(
    machine_type: str | None = None,
    count: int = 0,
    page: int = 0,
) -> str | list:
    """Fetch nodes from the Paddles API with optional filtering.

    Args:
        machine_type: Filter nodes by machine type.
        count: Number of nodes to return (for pagination).
        page: Page number to fetch (for pagination).
    """
    try:
        client = get_paddles_client()
        return client.node(
            machine_type=machine_type,
            count=count,
            page=page,
        )
    except Exception as e:
        return f"Error fetching nodes: {e}"


@mcp.tool()
def get_cluster_health(
    days: int = 30,
    branch: str | None = None,
    suite: str | None = None,
) -> str | dict:
    """Assess overall cluster health for the last N days.

    Returns the health badge (Healthy, Degraded, Critical), reasons,
    active/completed test runs, in-flight jobs, worst performing branch,
    average job duration, and stuck job counts.

    Args:
        days: Number of days of history to retrieve (default is 30).
        branch: Filter health assessment to a specific branch.
        suite: Filter health assessment to a specific suite.
    """
    try:
        from datetime import datetime, timedelta, timezone
        from dataclasses import asdict

        get_paddles_client()

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        runs_stats = TestRunsStats.since(
            cutoff=cutoff,
            branch=branch or "",
            suite=suite or "",
        )
        jobs_stats = JobsStats.for_testruns(runs_stats.testruns)

        health = runs_stats.cluster_health(jobs_stats)
        return asdict(health)
    except Exception as e:
        return f"Error assessing cluster health: {e}"


@mcp.tool()
def get_top_failures(
    branch: str | None = None,
    suite: str | None = None,
    count: int = 10,
    days: int = 30,
) -> str | list[dict]:
    """Retrieve the top failure reasons for jobs in the last N days.

    Args:
        branch: Filter jobs by branch name.
        suite: Filter jobs by suite name.
        count: Maximum number of failure reasons to return (default is 10).
        days: Number of days of job history to retrieve (default is 30).
    """
    try:
        from datetime import datetime, timedelta, timezone
        from dataclasses import asdict

        get_paddles_client()

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        runs_stats = TestRunsStats.since(
            cutoff=cutoff,
            branch=branch or "",
            suite=suite or "",
        )
        jobs_stats = JobsStats.for_testruns(runs_stats.testruns)

        reasons = jobs_stats.top_failure_reasons(n=count)
        return [asdict(r) for r in reasons]
    except Exception as e:
        return f"Error retrieving top failures: {e}"


@mcp.tool()
def get_flaky_tests(
    branch: str | None = None,
    suite: str | None = None,
    days: int = 30,
    min_executions: int = 3,
) -> str | list[dict]:
    """Identify and score flaky tests (failing/passing on the same SHA).

    Args:
        branch: Filter jobs by branch name.
        suite: Filter jobs by suite name.
        days: Number of days of history to analyze (default is 30).
        min_executions: Minimum number of job executions to consider a
          test (default is 3).
    """
    try:
        from datetime import datetime, timedelta, timezone
        from dataclasses import asdict

        get_paddles_client()

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        runs_stats = TestRunsStats.since(
            cutoff=cutoff,
            branch=branch or "",
            suite=suite or "",
        )
        jobs_stats = JobsStats.for_testruns(runs_stats.testruns)

        flaky = jobs_stats.flaky_tests(min_executions=min_executions)
        return [asdict(f) for f in flaky]
    except Exception as e:
        return f"Error retrieving flaky tests: {e}"


@mcp.tool()
def get_hardware_reliability(
    days: int = 30,
) -> str | dict:
    """Analyze machine-type reliability and architecture mapping.

    Args:
        days: Number of days of history to analyze (default is 30).
    """
    try:
        from datetime import datetime, timedelta, timezone
        from dataclasses import asdict

        get_paddles_client()

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        runs_stats = TestRunsStats.since(cutoff=cutoff)
        jobs_stats = JobsStats.for_testruns(runs_stats.testruns)

        arch_map = HardwareStats.load_arch_map()
        hw_stats = HardwareStats.from_testruns_jobs(
            runs_stats, jobs_stats, arch_by_machine_type=arch_map
        )

        reliability = hw_stats.jobs.reliability_by("machine_type")
        return {
            "machine_types": hw_stats.machine_types(),
            "reliability": [asdict(r) for r in reliability],
            "arch_by_machine_type": hw_stats.arch_by_machine_type,
        }
    except Exception as e:
        return f"Error retrieving hardware reliability: {e}"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the Paddles MCP Server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport protocol to use (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help=(
            "Host address to bind to when running SSE or HTTP "
            "(default: 0.0.0.0)"
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on when running SSE or HTTP (default: 8000)",
    )

    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    elif args.transport == "sse":
        mcp.run(transport="sse", host=args.host, port=args.port)
    elif args.transport == "streamable-http":
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
        )
