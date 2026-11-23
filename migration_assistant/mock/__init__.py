"""Mock mode: try the app without some or all of its outside services. Each part is switched on by itself:

- MOCK_AZURE=1     Discover reads mock_data/hackaton-2026-rg.json (a scrubbed copy of the real group) instead of `az`.
- MOCK_AI=1        Every AI request gets a canned answer. No tokens are spent.
- MOCK_LEASEWEB=1  The app starts with a mock key, and Leaseweb calls go to a fake Leaseweb API that follows the specs.
- MOCK_MODE=1      All three.

They can be set in the environment, in .env, or with the start scripts (--mock, --mock-azure, ...). MOCK_DELAY scales
the short pauses that make loading states visible (default 1, 0 for none). Results are saved to data/mock-state.json,
and every page and export says what was mocked. One module per part: azure.py, ai.py, leaseweb.py.
"""
from pathlib import Path

from .ai import MOCK_PROVIDER, MockAI
from .azure import FIXTURE, MockAzure
from .leaseweb import FakeLeaseweb, MockHttp, MockResponse

PARTS = ("azure", "ai", "leaseweb")
TRUE = ("1", "true", "yes", "on")
MOCK_STATE_FILE = Path("data/mock-state.json")
MOCK_KEY = "mock-leaseweb-key"
DESCRIBE = {"azure": "Azure is a saved copy of hackaton-2026-rg (az is not used)",
            "ai": "the AI gives canned answers (no tokens are spent)",
            "leaseweb": "Leaseweb is a fake API with a mock key (nothing is sent)"}

__all__ = ["FIXTURE", "MOCK_KEY", "MOCK_PROVIDER", "MOCK_STATE_FILE", "PARTS", "FakeLeaseweb", "MockAI", "MockAzure",
           "MockHttp", "MockResponse", "delay_from", "describe", "mock_overrides", "mock_parts"]


def mock_parts(environ) -> set[str]:
    """Which parts are mocked: MOCK_MODE turns on all of them, MOCK_AZURE / MOCK_AI / MOCK_LEASEWEB one each."""
    on = lambda name: str(environ.get(name, "")).strip().lower() in TRUE
    return set(PARTS) if on("MOCK_MODE") else {p for p in PARTS if on(f"MOCK_{p.upper()}")}


def delay_from(environ) -> float:
    """MOCK_DELAY as a number (1 when unset or not a number; never negative)."""
    try:
        return max(0.0, float(environ.get("MOCK_DELAY", "1")))
    except ValueError:
        return 1.0


def describe(parts) -> str:
    """One sentence for the banner, the console and the exports."""
    mocked = [DESCRIBE[p] for p in PARTS if p in parts]
    real = [p.capitalize() if p != "ai" else "AI" for p in PARTS if p not in parts]
    text = "Mock mode: " + "; ".join(mocked) + "."
    return text + (f" Real: {', '.join(real)}." if real else " Nothing leaves this machine.")


def mock_overrides(parts, delay: float = 0.0) -> dict:
    """create_app() keyword arguments for the mocked parts. Each part brings everything it needs, so a part
    can never be half on (a mock key without the fake API, a mock answer without the mock provider).
    `delay` scales the pauses (0: none)."""
    parts = set(parts)
    if not parts:
        return {}
    kw: dict = {"notice": describe(parts), "state_file": MOCK_STATE_FILE}
    if "azure" in parts:
        azure = MockAzure(delay)
        # The mock subscription is never remembered, so it cannot replace the real choice.
        kw.update(discover=azure.discover, groups_fn=azure.groups, azure_status_fn=azure.status,
                  subscriptions_fn=azure.subscriptions, settings_file=None)
    if "ai" in parts:
        ai = MockAI(delay)
        kw.update(ask=ai.ask, models_fn=ai.models, ai_providers=[MOCK_PROVIDER])
    if "leaseweb" in parts:
        from ..dryrun import default_http
        # The public Azure price list stays real unless Azure is mocked too (then nothing leaves the machine).
        kw.update(http=MockHttp(None if "azure" in parts else default_http(), delay=delay), api_key=MOCK_KEY,
                  wait_timeout=30)
    return kw
