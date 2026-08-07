import streamlit as st

from libs.paddle import Paddles


@st.cache_data(ttl=60)
def get_runs(count: int = 100, page: int = 1):
    """Fetch the latest runs from Paddles."""
    return Paddles().run(count=count, page=page)


@st.cache_data(ttl=60)
def get_run(run_name: str):
    """Fetch a single run by name."""
    return Paddles().run(run_name=run_name)


@st.cache_data(ttl=60)
def get_runs_by_branch(branch: str, count: int = 100):
    """Fetch runs filtered by exact branch name."""
    return Paddles().run(branch=branch, count=count)


@st.cache_data(ttl=60)
def get_runs_by_suite(suite: str, count: int = 100):
    """Fetch runs filtered by suite."""
    return Paddles().run(suite=suite, count=count)


@st.cache_data(ttl=60)
def get_jobs_for_run(run_name: str):
    """Fetch all jobs belonging to a specific run."""
    return Paddles().jobs_for_run(run_name)


@st.cache_data(ttl=60)
def get_job(run_name: str, job_id: str):
    """Fetch a single job by run name and job ID."""
    return Paddles().job(run_name=run_name, job_id=job_id)


@st.cache_data(ttl=60)
def get_jobs_by_status(status: str, count: int = 100):
    """Fetch jobs filtered by status."""
    return Paddles().jobs(status=status, count=count)


@st.cache_data(ttl=60)
def get_jobs_by_machine_type(machine_type: str, count: int = 100):
    """Fetch jobs filtered by machine type."""
    return Paddles().jobs(machine_type=machine_type, count=count)


@st.cache_data(ttl=120)
def get_nodes(machine_type: str | None = None):
    """Fetch machine/node information."""
    return Paddles().node(machine_type=machine_type)


def clear_cache():
    """Clear all cached API responses."""
    st.cache_data.clear()
