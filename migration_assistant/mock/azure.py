"""Mock Azure: Discover reads a saved, scrubbed copy of hackaton-2026-rg instead of calling `az`.
Rebuild the data with scripts/make_mock_fixture.py."""
import json
from pathlib import Path

from ..azure_discovery import DiscoveryError
from ..models import Resource
from ._pause import pause

FIXTURE = Path(__file__).resolve().parent.parent / "mock_data" / "hackaton-2026-rg.json"
MOCK_SUB = "00000000-0000-4000-8000-000000000000"


class MockAzure:
    fake = True  # create_app shows the Azure badge as mocked

    def __init__(self, delay: float = 0.0, fixture: Path = FIXTURE):
        self.delay, self.fixture = delay, fixture

    def _data(self) -> dict:
        return json.loads(self.fixture.read_text(encoding="utf-8"))

    def discover(self, resource_group: str, subscription: str | None = None) -> list[Resource]:
        data = self._data()
        if resource_group != data["resource_group"]:
            raise DiscoveryError(f"Mock Azure only has the resource group '{data['resource_group']}'.")
        pause(self.delay, 0.8)
        return [Resource(**r) for r in data["resources"]]

    def groups(self, subscription: str | None = None) -> list[dict]:
        data = self._data()
        return [{"name": data["resource_group"], "location": data["location"]}]

    def status(self) -> dict:
        return {"installed": True, "signed_in": True, "user": "mock.user@example.com",
                "subscription": {"id": MOCK_SUB, "name": "Mock subscription"}, "tenant": "mock-tenant", "message": ""}

    def subscriptions(self) -> list[dict]:
        return [{"id": MOCK_SUB, "name": "Mock subscription", "is_default": True}]
