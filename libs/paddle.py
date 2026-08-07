from urllib.parse import quote

import requests

from libs.config import get_paddle_config
from libs.exceptions import PaddlesAPIError


class Paddles:
    def __init__(self):
        self.config = get_paddle_config()

        self.base_url = self.config["base_url"]
        self.timeout = int(self.config["timeout"])
        self.tls_verify = self.config["tls_verify"]

    def _get(self, endpoint: str, params: dict | None = None):
        """Fetch data from the Paddles API."""
        url = f"{self.base_url.rstrip('/')}{endpoint}"
        try:
            response = requests.get(
                url,
                params=params or {},
                timeout=self.timeout,
                verify=self.tls_verify,
            )
            if response.status_code == 200:
                return response.json()
            if response.status_code == 404:
                raise PaddlesAPIError(f"404: Not found at {url}")
            raise PaddlesAPIError(
                f"{response.status_code}: {response.text} at {url}"
            )
        except requests.exceptions.RequestException as e:
            raise PaddlesAPIError(f"Connection error: {e}") from e

    @staticmethod
    def _path_segment(value: str) -> str:
        """URL-encode a single path segment."""
        return quote(str(value), safe="")

    def run(
        self,
        run_name: str | None = None,
        branch: str | None = None,
        suite: str | None = None,
        status: str | None = None,
        user: str | None = None,
        count: int = 0,
        page: int = 0,
    ):
        """Fetch runs from the Paddles API.

        Single-run lookup uses ``/runs/{name}/``. Filters use path segments
        (e.g. ``/runs/branch/{branch}/status/{status}/``). Pagination uses
        query params.
        """
        params: dict = {}
        if count and count > 0:
            params["count"] = count
        if page and page > 0:
            params["page"] = page

        if run_name:
            return self._get(
                f"/runs/{self._path_segment(run_name)}/",
            )

        parts: list[str] = []
        if branch:
            parts.extend(["branch", self._path_segment(branch)])
        if suite:
            parts.extend(["suite", self._path_segment(suite)])
        if status:
            parts.extend(["status", self._path_segment(status)])
        if user:
            parts.extend(["user", self._path_segment(user)])

        if parts:
            return self._get(f"/runs/{'/'.join(parts)}/", params=params)
        return self._get("/runs/", params=params)

    def jobs_for_run(self, run_name: str):
        """Fetch all jobs for a run."""
        return self._get(
            f"/runs/{self._path_segment(run_name)}/jobs/"
        )

    def job(self, run_name: str, job_id: str):
        """Fetch a single job by run name and job ID."""
        return self._get(
            f"/runs/{self._path_segment(run_name)}/jobs/"
            f"{self._path_segment(job_id)}/"
        )

    def jobs(
        self,
        status: str | None = None,
        branch: str | None = None,
        suite: str | None = None,
        sha1: str | None = None,
        os_type: str | None = None,
        user: str | None = None,
        machine_type: str | None = None,
        count: int = 0,
        page: int = 0,
    ):
        """Fetch jobs from the Paddles API.

        Jobs list filters are query parameters (not path segments).
        """
        params: dict = {}
        if branch:
            params["branch"] = branch
        if suite:
            params["suite"] = suite
        if sha1:
            params["sha1"] = sha1
        if os_type:
            params["os_type"] = os_type
        if user:
            params["user"] = user
        if machine_type:
            params["machine_type"] = machine_type
        if status:
            params["status"] = status
        if count and count > 0:
            params["count"] = count
        if page and page > 0:
            params["page"] = page
        return self._get("/jobs/", params=params)

    def node(
        self,
        machine_type: str | None = None,
        count: int = 0,
        page: int = 0,
    ):
        """Fetch nodes from the Paddles API.

        Node filters are query parameters (not path segments).
        """
        params: dict = {}
        if machine_type:
            params["machine_type"] = machine_type
        if count and count > 0:
            params["count"] = count
        if page and page > 0:
            params["page"] = page
        return self._get("/nodes/", params=params)
