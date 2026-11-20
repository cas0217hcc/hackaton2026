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


from migration_assistant.leaseweb_ops import find_operations, load_operation_docs


def test_operation_docs_describe_the_call_from_the_spec():
    docs = load_operation_docs()
    d = docs["createObjectStorageBucket"]
    assert d["method"] == "POST" and d["path"] == "/objectStorage/v1/objectStorages/{objectStorageId}/buckets"
    assert d["summary"] == "Create an object storage bucket" and "tenant bucket" in d["description"]
    assert d["path_params"] == ["objectStorageId"]
    fields = {f["name"]: f for f in d["body_fields"]}
    assert fields["name"]["required"] is True and fields["isVersioningEnabled"]["required"] is True
    assert fields["quota"]["required"] is False and fields["name"]["type"] == "string"


def test_operation_docs_resolve_referenced_property_schemas():
    fields = {f["name"]: f for f in load_operation_docs()["launchInstance"]["body_fields"]}
    assert "eu-west-3" in fields["region"]["enum"] and fields["region"]["required"] is True
    assert fields["contractType"]["enum"] == ["HOURLY", "MONTHLY"]
    assert fields["rootDiskSize"]["type"] == "integer"


def test_operation_without_a_body_has_no_body_fields():
    d = load_operation_docs()["addToPrivateNetwork"]
    assert d["body_fields"] == [] and d["path_params"] == ["instanceId"]


def test_find_operations_picks_ids_out_of_free_text_in_order():
    ids = {"createObjectStorageUser", "createObjectStorageGroup", "launchInstance", "post/privateNetworks", "getInstance"}
    text = "Create a user with createObjectStorageUser, and a group with createObjectStorageGroup; then post/privateNetworks and launchInstance."
    assert find_operations(text, ids) == ["createObjectStorageUser", "createObjectStorageGroup", "post/privateNetworks", "launchInstance"]


def test_find_operations_ignores_look_alike_words_and_repeats():
    ids = {"getInstance", "launchInstance"}
    assert find_operations("call getInstanceList then launchInstance and launchInstance again, not relaunchInstance", ids) == ["launchInstance"]
    assert find_operations("", ids) == [] and find_operations("nothing here", ids) == []
