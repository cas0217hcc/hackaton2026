from migration_assistant.leaseweb_ops import load_operations


def test_known_operations_present():
    ops = load_operations()
    for name in ("createObjectStorageBucket", "createSecurityGroup", "getInstanceList"):
        assert name in ops


def test_operation_has_method_and_path():
    method, path = load_operations()["createObjectStorageBucket"]
    assert method == "POST"
    assert path.startswith("/objectStorage/v1/")
