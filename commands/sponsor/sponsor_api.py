import json

import aiohttp

from dataConfig import SPONSOR_API, SPONSOR_API_URL

BASE_URL = SPONSOR_API_URL.rstrip("/")
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)

class SponsorApiError(Exception):

class SponsorApi:

    def __init__(self, actor_guid: str, actor_name: str):
        self._actor = json.dumps({"Guid": str(actor_guid), "Name": str(actor_name)})

    def _headers(self) -> dict:
        return {
            "Authorization": f"SS14Token {SPONSOR_API}",
            "Content-Type": "application/json",
            "Actor": self._actor,
        }

    async def _request(self, method: str, path: str, body: dict | None = None, params: dict | None = None):
        url = BASE_URL + path

        try:
            async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                async with session.request(
                    method,
                    url,
                    json=body,
                    params=params,
                    headers=self._headers(),
                ) as response:
                    text = await response.text()

                    if response.status >= 400:
                        raise SponsorApiError(_describe_error(response.status, text))

                    if not text:
                        return None

                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        raise SponsorApiError(f"Сервер вернул не JSON:\n{text[:500]}")
        except aiohttp.ClientError as error:
            raise SponsorApiError(f"Сервер недоступен: {error}") from error

    async def get_tiers(self) -> list:
        return await self._request("GET", "/admin/sponsors/tiers") or []

    async def create_tier(self, body: dict) -> dict:
        return await self._request("POST", "/admin/sponsors/tiers/create", body=body)

    async def update_tier(self, body: dict) -> dict:
        return await self._request("POST", "/admin/sponsors/tiers/update", body=body)

    async def delete_tier(self, name: str):
        return await self._request("POST", "/admin/sponsors/tiers/delete", body={"name": name})

    async def get_discord_roles(self) -> dict:
        return await self._request("GET", "/admin/sponsors/discord_roles") or {}

    async def get_player(self, query: str) -> dict:
        key = "userId" if _looks_like_guid(query) else "userName"
        return await self._request("GET", "/admin/sponsors/player", params={key: query})

    async def create_grant(self, body: dict) -> dict:
        return await self._request("POST", "/admin/sponsors/grants/create", body=body)

    async def update_grant(self, body: dict) -> dict:
        return await self._request("POST", "/admin/sponsors/grants/update", body=body)

    async def revoke_grant(self, grant_id: int):
        return await self._request("POST", "/admin/sponsors/grants/revoke", body={"id": grant_id})


def _looks_like_guid(value: str) -> bool:
    parts = value.split("-")
    return len(parts) == 5 and len(value) == 36

def _describe_error(status: int, text: str) -> str:
    if status == 401:
        if "disabled" in text.lower():
            return (
                "Спонсорское API выключено. "
            )

        return "Неверный токен (Код 401)."

    try:
        payload = json.loads(text)
        message = payload.get("Message") or payload.get("message")
    except (json.JSONDecodeError, AttributeError):
        message = None

    if message:
        return f"{message} (HTTP {status})"

    return f"HTTP {status}: {text[:300]}"
