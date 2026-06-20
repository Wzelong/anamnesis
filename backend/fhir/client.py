"""Async FHIR HTTP client with bearer auth."""
import httpx


class FhirClient:
    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _url(self, path: str) -> str:
        if not path:
            return self.base_url
        return f"{self.base_url}/{path.lstrip('/')}"

    def _headers(self, writing: bool = False) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/fhir+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if writing:
            headers["Content-Type"] = "application/fhir+json"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict | None = None,
    ) -> httpx.Response:
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.request(
                method,
                self._url(path),
                headers=self._headers(writing=json_body is not None),
                params=params,
                json=json_body,
            )

    async def read(self, path: str) -> dict | None:
        response = await self._request("GET", path)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    async def search(
        self,
        resource_type: str,
        params: dict[str, str] | None = None,
    ) -> dict | None:
        response = await self._request("GET", resource_type, params=params)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    async def post(self, path: str, body: dict) -> dict:
        response = await self._request("POST", path, json_body=body)
        response.raise_for_status()
        return response.json()

    async def put(self, path: str, body: dict) -> dict:
        response = await self._request("PUT", path, json_body=body)
        response.raise_for_status()
        return response.json()

    async def delete(self, path: str) -> None:
        response = await self._request("DELETE", path)
        if response.status_code in (404, 410):
            return
        response.raise_for_status()

    async def transaction(self, bundle: dict) -> dict:
        response = await self._request("POST", "", json_body=bundle)
        response.raise_for_status()
        return response.json()

    async def validate(
        self, resource_type: str, resource: dict, profile: str | None = None,
    ) -> tuple[int, dict | None]:
        """POST {type}/$validate (optionally ?profile=). Returns (status, body)
        without raising — $validate reports issues in an OperationOutcome, not
        via the HTTP status."""
        params = {"profile": profile} if profile else None
        response = await self._request("POST", f"{resource_type}/$validate", params=params, json_body=resource)
        try:
            return response.status_code, response.json()
        except Exception:
            return response.status_code, None
