import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime, timedelta

def get_jobs_data():
    """Generate mock data for teuthology jobs"""
    _, jobs = _generate_connected_data()
    return jobs


def get_runs_data():
    """Generate mock data for teuthology runs"""
    runs, _ = _generate_connected_data()
    return runs


@st.cache_data
def _generate_connected_data():
    """
    Generate mock data for teuthology runs and jobs with a one-to-many relationship.
    A run can have between 10 and 20 jobs.
    """
    num_runs = 10
    runs_data = []
    jobs_data = []
    job_counter = 0

    for i in range(num_runs):
        run_name = f"run-{i}-{np.random.choice(["ubuntu", "centos", "debian"])}"
        num_jobs_for_run = np.random.randint(10, 21)

        run_job_ids = [str(job_counter + j) for j in range(num_jobs_for_run)]

        run = {
            "name": run_name,
            "status": np.random.choice(["pass", "fail", "running", "queued"]),
            "user": np.random.choice(["user-a", "user-b", "user-c"]),
            "scheduled": (
                datetime.now() - timedelta(minutes=np.random.randint(0, 1440))
            ).isoformat(),
            "posted": (
                datetime.now() - timedelta(minutes=np.random.randint(0, 720))
            ).isoformat(),
            "job_ids": run_job_ids,
        }
        runs_data.append(run)

        for j in range(num_jobs_for_run):
            job = {
                "job_id": str(job_counter),
                "run_name": run_name,
                "success": np.random.choice([True, False]),
                "status": np.random.choice(["pass", "fail", "running", "queued"]),
                "description": f"job description {job_counter}",
                "machine_type": np.random.choice(["type-a", "type-b"]),
                "os_type": np.random.choice(["ubuntu", "centos"]),
                "duration": np.random.uniform(300, 3600),
                "owner": np.random.choice(["owner-x", "owner-y"]),
                "posted": (
                    datetime.now() - timedelta(minutes=np.random.randint(0, 720))
                ).isoformat(),
            }
            jobs_data.append(job)
            job_counter += 1

    return pd.DataFrame(runs_data).to_dict("records"), pd.DataFrame(
        jobs_data
    ).to_dict("records")
