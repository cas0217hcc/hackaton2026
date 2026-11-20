import socket

from migration_assistant.assess import RULES
from migration_assistant.dryrun import DryRunExecutor, build_calls
from migration_assistant.models import Assessment


def a(name, rule_type):
    r = RULES[rule_type]
    return Assessment(name, r.route, r.target, r.rationale, list(r.lw_operations))


def test_rebuild_resources_excluded():
    calls = build_calls([a("kv", "Microsoft.KeyVault/vaults")])
    assert calls == []


def test_calls_use_spec_method_and_path():
    calls = build_calls([a("st", "Microsoft.Storage/storageAccounts")])
    assert calls[0].method == "POST"
    assert calls[0].path.startswith("/objectStorage/v1/")
    assert calls[0].operation_id == "createObjectStorageBucket"


def test_dry_run_executor_sends_nothing(monkeypatch):
    def boom(*args, **kw):
        raise AssertionError("network used")
    monkeypatch.setattr(socket, "socket", boom)
    call = build_calls([a("st", "Microsoft.Storage/storageAccounts")])[0]
    result = DryRunExecutor().execute(call)
    assert result["sent"] is False and result["dry_run"] is True
