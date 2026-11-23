import pytest

MOCK_VARS = ("MOCK_MODE", "MOCK_AZURE", "MOCK_AI", "MOCK_LEASEWEB")


@pytest.fixture(autouse=True)
def no_mock_switches_from_the_developer(monkeypatch):
    """A developer's shell or .env may switch mocks on; the tests must not depend on it. MOCK_DELAY=0 keeps the
    mock pauses out of the test run."""
    for name in MOCK_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MOCK_DELAY", "0")
