"""Connection checks: Azure sign-in and subscription, Leaseweb key verification, AI readiness gate."""
import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from migration_assistant import app as app_module
from migration_assistant.app import create_app
from migration_assistant.azure_discovery import (DiscoveryError, azure_status, friendly_error, list_resource_groups,
                                                 list_resources, list_subscriptions)
from migration_assistant.models import Resource

KEY = "lsw-secret-key-123"
VM = Resource("/x/vm", "vm-web-01", "Microsoft.Compute/virtualMachines", "westeurope")
KV = Resource("/x/kv", "kv-hack", "Microsoft.KeyVault/vaults", "westeurope")
SUBS = [{"id": "sub-a", "name": "Alpha", "is_default": True}, {"id": "sub-b", "name": "Beta", "is_default": False}]


def proc(stdout="", code=0, stderr=""):
    return lambda cmd, **kw: subprocess.CompletedProcess(cmd, code, stdout, stderr)


# ---- az helpers

def test_azure_status_signed_in():
    out = json.dumps({"id": "sub-a", "name": "Alpha", "tenantId": "t1", "user": {"name": "dev@example.com"}})
    s = azure_status(proc(out))
    assert s["signed_in"] and s["user"] == "dev@example.com" and s["subscription"] == {"id": "sub-a", "name": "Alpha"}


def test_azure_status_not_signed_in_and_not_installed():
    s = azure_status(proc(code=1, stderr="ERROR: Please run 'az login' to setup account."))
    assert s["installed"] and not s["signed_in"] and "az login" in s["message"]

    def missing(cmd, **kw):
        raise FileNotFoundError
    s = azure_status(missing)
    assert not s["installed"] and "not found" in s["message"]


@pytest.mark.parametrize("stderr,expected", [
    ("ERROR: AADSTS700082: The refresh token has expired", "az login"),
    ("ERROR: (ResourceGroupNotFound) Resource group 'nope' could not be found.", "was not found"),
    ("ERROR: (AuthorizationFailed) The client does not have authorization", "Reader role"),
    ("WARNING: something\nERROR: weird failure", "weird failure"),
])
def test_friendly_errors(stderr, expected):
    assert expected in friendly_error(stderr, "nope")


def test_subscription_is_passed_to_az():
    seen = []

    def run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "[]", "")
    list_resource_groups(run, subscription="sub-b")
    with pytest.raises(DiscoveryError):
        list_resources("rg", run, subscription="sub-b")
    assert all(c[-2:] == ["--subscription", "sub-b"] for c in seen)


def test_list_subscriptions_sorted():
    out = json.dumps([{"id": "2", "name": "beta", "isDefault": False}, {"id": "1", "name": "Alpha", "isDefault": True}])
    assert [x["name"] for x in list_subscriptions(proc(out))] == ["Alpha", "beta"]


# ---- endpoints

def client(**kw):
    kw.setdefault("discover", lambda rg, subscription=None: [VM, KV])
    kw.setdefault("ask", lambda p: {"proposal": "x", "lw_operations": []})
    return TestClient(create_app(state_file=None, azure_status_fn=lambda: {"installed": True, "signed_in": True, "user": "u",
                                                                             "subscription": {"id": "sub-a", "name": "Alpha"}, "tenant": "", "message": ""},
                                 subscriptions_fn=lambda: SUBS, **kw))


def test_subscription_choice_is_validated_and_used_by_discover():
    used = []
    c = client(discover=lambda rg, subscription=None: used.append(subscription) or [VM])
    assert c.post("/api/azure/subscription", data={"subscription_id": "sub-zzz"}).status_code == 400
    assert c.post("/api/azure/subscription", data={"subscription_id": "sub-b"}).json() == {"selected": "sub-b"}
    assert c.get("/api/azure").json()["selected_subscription"] == "sub-b"
    c.post("/api/discover", data={"resource_group": "rg"})
    assert used == ["sub-b"]
    c.post("/api/reset")
    assert c.get("/api/state").json()["subscription"] == "sub-b"  # a setting survives Start over


def test_discover_rejects_invalid_group_names():
    c = client()
    assert c.post("/api/discover", data={"resource_group": "bad name; rm"}).status_code == 400
    assert c.post("/api/discover", data={"resource_group": "ok-name_1.(x)"}).status_code == 200


class KeyHttp:
    def __init__(self, status=200, exc=None):
        self.status, self.exc, self.calls = status, exc, []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        if self.exc:
            raise self.exc
        status = self.status

        class R:
            status_code = status

            @staticmethod
            def json():
                return {"instances": []}
        return R()


def test_key_verified():
    http = KeyHttp(200)
    c = client(http=http)
    c.post("/api/key", data={"api_key": KEY})
    r = c.post("/api/key/test").json()
    assert r["key_verified"] is True and KEY not in json.dumps(r)
    assert http.calls[0][0] == "GET" and http.calls[0][1].endswith("/publicCloud/v1/instances")
    assert c.get("/api/state").json()["key_verified"] is True


def test_rejected_key_is_removed():
    c = client(http=KeyHttp(401))
    c.post("/api/key", data={"api_key": KEY})
    r = c.post("/api/key/test")
    assert r.status_code == 400 and "rejected" in r.json()["error"]
    assert c.get("/api/state").json()["api_key_set"] is False


def test_unreachable_leaseweb_keeps_the_key_unverified():
    c = client(http=KeyHttp(exc=RuntimeError("offline")))
    c.post("/api/key", data={"api_key": KEY})
    r = c.post("/api/key/test").json()
    assert r["api_key_set"] is True and r["key_verified"] is None and "network" in r["detail"]


def test_key_test_without_a_key():
    assert client().post("/api/key/test").status_code == 409


def test_plan_is_refused_when_the_ai_provider_is_not_ready(monkeypatch):
    monkeypatch.setattr(app_module, "available_providers", lambda s: [
        {"id": "claude-cli", "label": "Claude Code (CLI)", "available": False, "detail": "claude command not found on PATH"}])
    c = TestClient(create_app(state_file=None, discover=lambda rg: [VM, KV], make_ask=app_module.default_make_ask,
                              azure_status_fn=lambda: {}, subscriptions_fn=lambda: []))
    # Assess still works for known types (the AI dependency check just reports its failure)
    monkeypatch.setattr(app_module, "add_dependencies", lambda *a, **k: "")
    c.post("/api/discover", data={"resource_group": "rg"})
    assert c.post("/api/assess").status_code == 200
    r = c.post("/api/plan", data={"source_dirs": ""})
    assert r.status_code == 409 and "not found on PATH" in r.json()["error"]
    assert "not ready" in c.get("/api/ai").json()["problem"]
