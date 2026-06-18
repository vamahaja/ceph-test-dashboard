import streamlit as st
import requests
from libs.config import get_base_url


@st.cache_data(ttl=60)
def fetch_api_data(endpoint: str, timeout: int = 15, verify: bool = False):
    """Fetch data from the Paddles API with basic error handling."""
    url = f"{get_base_url().rstrip('/')}{endpoint}"
    try:
        response = requests.get(url, timeout=timeout, verify=verify)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            st.warning(f"Data not found at {url}. (404)")
            return None
        else:
            st.error(f"Failed to fetch data. Status code: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"Connection error: {e}")
        return None


@st.cache_data(ttl=60)
def get_runs(count: int = 100, page: int = 1):
    """Fetch the latest runs from Paddles."""
    return fetch_api_data(f"/runs/?count={count}&page={page}")


@st.cache_data(ttl=60)
def get_run(run_name: str):
    """Fetch a single run by name."""
    return fetch_api_data(f"/runs/{run_name}/")


@st.cache_data(ttl=60)
def get_runs_by_branch(branch: str, count: int = 100):
    """Fetch runs filtered by exact branch name."""
    return fetch_api_data(f"/runs/branch/{branch}/?count={count}")


@st.cache_data(ttl=60)
def get_runs_by_suite(suite: str, count: int = 100):
    """Fetch runs filtered by suite."""
    return fetch_api_data(f"/runs/?suite={suite}&count={count}")


@st.cache_data(ttl=60)
def get_jobs_for_run(run_name: str):
    """Fetch all jobs belonging to a specific run."""
    return fetch_api_data(f"/runs/{run_name}/jobs/")


@st.cache_data(ttl=60)
def get_job(run_name: str, job_id: str):
    """Fetch a single job by run name and job ID."""
    return fetch_api_data(f"/runs/{run_name}/jobs/{job_id}/")


@st.cache_data(ttl=60)
def get_jobs_by_status(status: str, count: int = 100):
    """Fetch jobs filtered by status."""
    return fetch_api_data(f"/jobs/?status={status}&count={count}")


@st.cache_data(ttl=60)
def get_jobs_by_machine_type(machine_type: str, count: int = 100):
    """Fetch jobs filtered by machine type."""
    return fetch_api_data(f"/jobs/?machine_type={machine_type}&count={count}")


@st.cache_data(ttl=120)
def get_nodes(machine_type: str | None = None):
    """Fetch machine/node information."""
    endpoint = "/nodes/"
    if machine_type:
        endpoint += f"?machine_type={machine_type}"
    return fetch_api_data(endpoint)


def clear_cache():
    """Clear all cached API responses."""
    st.cache_data.clear()
