# Ceph Test Dashboard

A Streamlit web application to display Teuthology test runs from a Paddles API. This dashboard provides a user-friendly interface to view and analyze Teuthology test runs.

## Prerequisites

Before you begin, ensure you have the following installed:

1. **Access to paddles:** A running instance of the paddles REST API.
2. **Python 3.11+:** Recommended for compatibility with modern paddles environments.
3. **uv:** The extremely fast Python package manager.

## Steps to Deploy

1.  **Clone the repository:**

    ```bash
    git clone <your-repository-url> && cd ceph-test-dashboard
    ```

2.  **Install dependencies:**

    Install `uv`:

    ```bash
    pip install uv
    ```

    Sync environment:

    ```bash
    uv sync
    ```

3.  **Configure the application:**

    The dashboard requires a configuration file to specify the Paddles API endpoint. A template for this file is provided as `templates/config.ini.template`.

    Copy the template to your user configuration directory:
    ```bash
    mkdir -p ~/.config
    cp templates/config.ini.template ~/.config/ceph-test-dashboard.ini
    ```

    Then, edit `~/.config/ceph-test-dashboard.ini` and replace `http://paddles.example.com` with the actual URL of your Paddles instance.

    The file content should look like this:
    ```ini
    [paddles]
    base_url = http://paddles.example.com
    ```

4.  **Run the application:**

    Once configured, you can run the dashboard using Streamlit:

    ```bash
    uv run streamlit run app.py
    ```

    The application will be accessible in your web browser at the local URL provided by Streamlit (usually `http://localhost:8501`).

## Container Deployment

See [`deployment/README.md`](deployment/README.md) for full Podman deployment instructions.

## Pages

| Page | Path | Description |
|------|------|-------------|
| Dashboard | `pages/reports/dashboard.py` | Overview with KPIs, daily trends, status distribution, and top failures |
| Test Runs | `pages/reports/testruns.py` | Run-level analysis by branch, suite, and cloud platform |
| Jobs | `pages/reports/jobs.py` | Job-level detail, failure patterns, and duration analysis |
| Alerts | `pages/reports/alerts.py` | Automated alerts for high failure rates, dead jobs, and flaky suites |
| Releases | `pages/reports/release.py` | Release health dashboard for stable branches (tentacle, squid, umbrella) |
| Nightly | `pages/reports/nightly.py` | Nightly regression analysis with branch filtering, OS-wise breakdown, and job-level daily trends |
| Builds | `pages/reports/builds.py` | Build-centric analysis for a specific branch/commit SHA with health scorecard, per-SHA comparison, suite health, OS distribution, and failure drill-down |
| Search | `pages/tools/search.py` | Search runs and jobs |
| History | `pages/tools/history.py` | Historical trends |

## Architecture

The normalizer layer (`libs/normalizer.py`) fetches data from the Paddles API and normalises records into a consistent schema used by all dashboard pages.
