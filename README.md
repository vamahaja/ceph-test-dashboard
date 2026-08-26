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

### Dashboard

| Page | Path | Description |
|------|------|-------------|
| Overview | `pages/dashboard/overview.py` | Ops landing page: rolling-window cluster health, active runs, and job trends by OS |
| Test Runs | `pages/dashboard/testruns.py` | Run-level analysis by branch, suite, and cloud platform |
| Jobs | `pages/dashboard/jobs.py` | Job-level detail, failure patterns, and duration analysis |

### Reports

| Page | Path | Description |
|------|------|-------------|
| Releases | `pages/reports/release.py` | Release health dashboard for stable branches (tentacle, squid, umbrella) |
| Nightly | `pages/reports/nightly.py` | Nightly regression analysis with branch filtering, OS-wise breakdown, and job-level daily trends |
| Builds | `pages/reports/builds.py` | Build-centric analysis for a specific branch/commit SHA with health scorecard, per-SHA comparison, suite health, OS distribution, and failure drill-down |
| Coverage | `pages/reports/coverage.py` | Suite-centric view comparing coverage, failures, and flaky tests across branches |
| Hardware | `pages/reports/hardware.py` | Machine-type-centric reliability dashboard comparing branches, suites, and OS for a selected lab class |

### Tools

| Page | Path | Description |
|------|------|-------------|
| Search | `pages/tools/search.py` | Search runs and jobs |
| Alerts | `pages/tools/alerts.py` | Automated alerts for high failure rates, dead jobs, and flaky suites |
| Agent | `pages/tools/agent.py` | AI agent for asking questions about test runs, jobs, and failures |

## Architecture

Overview, Test Runs, Jobs, Releases, Nightly, Builds, Coverage, and Hardware load Paddles data through `libs/reports` (`TestRunsStats` / `JobsStats` / `HardwareStats`).
