from urllib.parse import quote

import requests

from libs.config import get_paddle_config
from libs.exceptions import PaddlesAPIError


class Paddles:
    def __init__(self):
        self.config = get_paddle_config()

        self.base_url = self.config["base_url"]
        self.timeout = self.config["timeout"]
        self.tls_verify = self.config["tls_verify"]

    def _get(self, endpoint: str, params: dict = None) -> dict:
        """Fetch data from the Paddles API"""
        url = f"{self.base_url.rstrip('/')}{endpoint}"
        if params is None:
            params = {}

        try:
            response = requests.get(
                url,
                timeout=self.timeout,
                verify=self.tls_verify,
            )
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                raise PaddlesAPIError(
                    f"404: Not found at {url}"
                )
            else:
                raise PaddlesAPIError(
                    f"{response.status_code}: "
                    f"{response.text} at {url}"
                )
        except requests.exceptions.RequestException as e:
            raise PaddlesAPIError(
                f"Connection error: {e}"
            ) from e
        except Exception as e:
            raise PaddlesAPIError(
                f"Unexpected error: {e}"
            ) from e

    def run(
        self,
        run_name: str | None = None,
        branch: str | None = None,
        suite: str | None = None,
        status: str | None = None,
        user: str | None = None,
        job_id: str | None = None,
        count: int = 0,
        page: int = 0,
    ) -> dict:
        """Fetch runs from the Paddles API"""
        url = "/runs/"
        if run_name:
            url += f"{run_name}"
        if branch:
            url += f"branch/{branch}/"
        if suite:
            url += f"suite/{suite}/"
        if status:
            url += f"status/{quote(status, safe='')}/"
        if user:
            url += f"user/{user}/"
        if job_id and run_name:
            url += f"jobs/{job_id}/"
        if count and count > 0:
            url += f"?count={count}"
        if page and page > 0 and count > 0:
            url += f"&page={page}"

        return self._get(url)

    def job(
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
    ) -> dict:
        """Fetch a job from the Paddles API"""
        url = "/jobs/"
        if branch:
            url += f"branch/{branch}/"
        if suite:
            url += f"suite/{suite}/"
        if sha1:
            url += f"sha1/{sha1}/"
        if os_type:
            url += f"os_type/{os_type}/"
        if user:
            url += f"user/{user}/"
        if machine_type:
            url += f"machine_type/{machine_type}/"
        if status:
            url += f"status/{quote(status, safe='')}/"
        if count and count > 0:
            url += f"?count={count}"
        if page and page > 0 and count > 0:
            url += f"&page={page}"

        return self._get(url)

    def node(
        self,
        machine_type: str | None = None,
        count: int = 0,
        page: int = 0,
    ) -> dict:
        """Fetch a node from the Paddles API"""
        url = "/nodes/"
        if machine_type:
            url += f"machine_type/{machine_type}/"
        if count and count > 0:
            url += f"?count={count}"
        if page and page > 0 and count > 0:
            url += f"&page={page}"

        return self._get(url)