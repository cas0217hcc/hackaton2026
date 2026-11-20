from migration_assistant.leaseweb_ops import load_operations


def test_known_operations_present():
    ops = load_operations()
    for name in ("createObjectStorageBucket", "createSecurityGroup", "getInstanceList"):
        assert name in ops


def test_operation_has_method_and_path():
    method, path = load_operations()["createObjectStorageBucket"]
    assert method == "POST"
    assert path.startswith("/objectStorage/v1/")


from migration_assistant.leaseweb_ops import load_launch_options


def test_region_options_have_locations_from_the_spec():
    regions = {r["value"]: r["description"] for r in load_launch_options()["region"]}
    assert regions["eu-west-3"] == "Amsterdam" and regions["eu-central-1"] == "Frankfurt"
    assert "ap-northeast-1" in regions  # in the spec enum even without a described example


def test_other_launch_options_come_from_spec_enums():
    opts = load_launch_options()
    assert "lsw.c3.large" in [o["value"] for o in opts["type"]]
    assert [o["value"] for o in opts["contractType"]] == ["HOURLY", "MONTHLY"]
    assert [o["value"] for o in opts["rootDiskStorageType"]] == ["LOCAL", "CENTRAL"]
