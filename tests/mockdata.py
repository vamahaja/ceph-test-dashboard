import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime, timedelta

# ── Seed constants ────────────────────────────────────────────────────────────
BRANCHES   = ["main", "squid", "reef", "quincy", "pacific", "tentacle"]
SUITES     = ["rados", "rbd", "rgw", "fs", "cephadm", "crimson", "dashboard"]
OS_TYPES   = ["ubuntu", "centos", "rhel"]
MACHINE_TYPES = ["smithi", "mira", "plana", "ovh"]
OWNERS     = ["teuthology", "user-a", "user-b", "user-c"]
CLOUD_PLATFORMS = ["bare-metal", "openstack", "aws"]

FAILURE_TEMPLATES = [
    "OSD crashed during scrub",
    "Timeout waiting for PG to become active",
    "Monitor election failed",
    "RGW bucket listing error",
    "MDS rank failed",
    "Network partition detected",
    "Disk full on OSD node",
    "RADOS bench write error",
    "CephFS mount failed",
    "Cephadm deploy failed",
    "Crimson OSD assertion",
    "Dashboard API timeout",
]


@st.cache_data
def _generate_connected_data():
    """
    Generate mock data for teuthology runs and jobs with a one-to-many
    relationship.  Mirrors the fields tracked by the OpenSearch dashboards:
      - teuthology-runs index  → runs_data
      - teuthology-jobs index  → jobs_data
    """
    rng = np.random.default_rng(42)
    num_runs = 60
    runs_data = []
    jobs_data = []
    job_counter = 0

    now = datetime.now()

    for i in range(num_runs):
        branch        = rng.choice(BRANCHES)
        suite         = rng.choice(SUITES)
        cloud_platform = rng.choice(CLOUD_PLATFORMS)
        sha_id        = f"{rng.integers(0x1000000, 0xfffffff):07x}"
        run_name      = f"{branch}-{suite}-{sha_id[:7]}-{i}"
        num_jobs      = int(rng.integers(8, 25))

        posted_dt  = now - timedelta(days=int(rng.integers(0, 90)),
                                     hours=int(rng.integers(0, 24)))
        sched_dt   = posted_dt - timedelta(minutes=int(rng.integers(5, 60)))

        results = {"pass": 0, "fail": 0, "dead": 0, "running": 0,
                   "waiting": 0, "queued": 0}

        run_job_ids = []
        for j in range(num_jobs):
            status = rng.choice(
                ["pass", "fail", "dead", "running", "queued"],
                p=[0.65, 0.18, 0.04, 0.07, 0.06]
            )
            results[status] = results.get(status, 0) + 1
            success = status == "pass"

            duration = float(rng.uniform(120, 1800) if success
                             else rng.uniform(300, 7200))

            failure_template = None
            if status in ("fail", "dead"):
                failure_template = rng.choice(FAILURE_TEMPLATES)

            job = {
                "job_id":           str(job_counter),
                "run_name":         run_name,
                "branch":           branch,
                "suite":            suite,
                "sha_id":           sha_id,
                "cloud_platform":   cloud_platform,
                "success":          success,
                "status":           status,
                "description":      f"{suite}/{branch} job {job_counter}",
                "machine_type":     rng.choice(MACHINE_TYPES),
                "os_type":          rng.choice(OS_TYPES),
                "duration":         round(duration, 1),
                "owner":            rng.choice(OWNERS),
                "failure_template": failure_template,
                "posted":           posted_dt.isoformat(),
            }
            jobs_data.append(job)
            run_job_ids.append(str(job_counter))
            job_counter += 1

        if results["running"] > 0:
            run_status = "running"
        elif results["queued"] > 0:
            run_status = "queued"
        elif results["fail"] > 0 or results["dead"] > 0:
            run_status = "fail"
        else:
            run_status = "pass"

        run = {
            "name":           run_name,
            "branch":         branch,
            "suite":          suite,
            "sha_id":         sha_id,
            "cloud_platform": cloud_platform,
            "status":         run_status,
            "user":           rng.choice(OWNERS),
            "scheduled":      sched_dt.isoformat(),
            "posted":         posted_dt.isoformat(),
            "job_ids":        run_job_ids,
            "results":        results,
            "total_jobs":     num_jobs,
        }
        runs_data.append(run)

    return (
        pd.DataFrame(runs_data).to_dict("records"),
        pd.DataFrame(jobs_data).to_dict("records"),
    )


def get_runs_data():
    """Return mock teuthology runs."""
    runs, _ = _generate_connected_data()
    return runs


def get_jobs_data(run_name=None, branch_name=None):
    """Return mock teuthology jobs, optionally filtered by run or branch."""
    _, jobs = _generate_connected_data()
    if run_name:
        jobs = [job for job in jobs if job["run_name"] == run_name]
    if branch_name:
        jobs = [job for job in jobs if job["branch"] == branch_name]
    return jobs
