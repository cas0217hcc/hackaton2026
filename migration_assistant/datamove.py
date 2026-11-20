"""Commands that copy the data itself, once the Leaseweb side exists.

The infrastructure calls create empty resources; these steps move what is inside them. They are
shown and exported for a person to run, never run by the app. Values the app cannot know are left
as <placeholders>.
"""
import re

from .models import Assessment, Resource

_SAFE = re.compile(r"[A-Za-z0-9][\w.-]*")


def _n(name: str) -> str:
    """A name that is safe to paste into a shell command, else a placeholder."""
    return name if _SAFE.fullmatch(name or "") else "<name>"


def _services(r: Resource) -> dict:
    return (r.properties or {}).get("services") or {}


def _storage(r: Resource) -> dict:
    acct = _n(r.name)
    services = _services(r)
    containers = services.get("containers")
    names = [_n(c) for c in containers] if containers else ["<container>"]
    commands = [
        f"rclone config create azure azureblob account={acct} env_auth=true",
        "rclone config create leaseweb s3 provider=Other endpoint=<object-storage-endpoint> "
        "access_key_id=<access-key> secret_access_key=<secret-key>",
    ] + [f"rclone sync azure:{c} leaseweb:{acct}/{c} --progress --checksum" for c in names]
    notes = ["env_auth uses your az login; the identity needs the Storage Blob Data Reader role.",
             "Create the access key with createObjectStorageAccessKey; the endpoint is shown with your Object Storage in the Leaseweb portal.",
             "Run the sync again just before cutover to copy what changed in between."]
    if services.get("queues"):
        notes.append(f"Queues ({', '.join(services['queues'])}): stop the producers and let the consumers drain them "
                     "before switching to the new broker; messages still in Azure are not copied.")
    if services.get("tables"):
        notes.append("Tables have no copy command here: export them with your own script into the database that replaces them.")
    if services.get("shares"):
        notes.append("File shares: mount the share and copy it with rsync to the instance or bucket that replaces it.")
    return {"title": "Copy the blobs to Object Storage", "commands": commands, "notes": notes}


def _cosmos(r: Resource) -> dict:
    acct = _n(r.name)
    script = "\n".join([
        "python3 - <<'PY'",
        "import json",
        "from azure.cosmos import CosmosClient",
        "from azure.identity import DefaultAzureCredential",
        f'client = CosmosClient("https://{acct}.documents.azure.com:443/", DefaultAzureCredential())',
        "for db in client.list_databases():",
        "    for cont in client.get_database_client(db['id']).list_containers():",
        "        items = client.get_database_client(db['id']).get_container_client(cont['id']).read_all_items()",
        "        with open(f\"{db['id']}.{cont['id']}.jsonl\", 'w') as out:",
        "            for item in items:",
        "                out.write(json.dumps({k: v for k, v in item.items() if not k.startswith('_')}) + '\\n')",
        "PY",
    ])
    return {
        "title": "Export Cosmos DB and import it into MongoDB",
        "commands": ["pip install azure-cosmos azure-identity", script,
                     "for f in *.jsonl; do db=${f%%.*}; coll=${f#*.}; coll=${coll%.jsonl}; "
                     "mongoimport --uri mongodb://<mongodb-host>:27017 --db \"$db\" --collection \"$coll\" --file \"$f\"; done"],
        "notes": ["The identity running the export needs the Cosmos DB Built-in Data Reader role (key auth may be disabled).",
                  "System fields (_rid, _etag, _ts, ...) are dropped. Each item keeps its id; map it to _id if the app expects that.",
                  "Writes made after the export are not copied: stop writes, or export again, at cutover."],
    }


def _keyvault(r: Resource) -> dict:
    vault = _n(r.name)
    return {
        "title": "Copy the secrets into HashiCorp Vault",
        "commands": [
            "export VAULT_ADDR=https://<vault-host>:8200   # and VAULT_TOKEN",
            f'az keyvault secret list --vault-name {vault} --query "[].name" -o tsv | while read -r name; do\n'
            f'  az keyvault secret show --vault-name {vault} --name "$name" --query value -o tsv | vault kv put "secret/$name" value=-\n'
            "done",
        ],
        "notes": ["Secret values go straight from az to vault through a pipe and are never printed.",
                  "Keys and certificates are not copied: re-issue them on the new side."],
    }


def _sql(r: Resource) -> dict:
    return {
        "title": "Export the Azure SQL databases",
        "commands": [f"sqlpackage /Action:Export /SourceServerName:{_n(r.name)}.database.windows.net "
                     "/SourceDatabaseName:<database> /TargetFile:<database>.bacpac /UniversalAuthentication:true"],
        "notes": ["A .bacpac imports into SQL Server. For PostgreSQL, convert the schema first (for example with pgloader)."],
    }


def _servicebus(r: Resource) -> dict:
    return {"title": "Drain the Service Bus queues", "commands": [],
            "notes": ["Messages are not copied: stop the senders, let the receivers empty the queues and topics, "
                      "then point both at RabbitMQ."]}


HANDLERS = {
    "microsoft.storage/storageaccounts": _storage,
    "microsoft.documentdb/databaseaccounts": _cosmos,
    "microsoft.keyvault/vaults": _keyvault,
    "microsoft.sql/servers": _sql,
    "microsoft.servicebus/namespaces": _servicebus,
}


def data_steps(resources: list[Resource], assessments: list[Assessment]) -> list[dict]:
    """One entry per resource that holds data: {resource, type, title, commands, notes}."""
    assessed = {a.resource_name for a in assessments if a.route != "included"}
    out = []
    for r in resources:
        handler = HANDLERS.get(r.type.lower())
        if handler and r.name in assessed:
            out.append({"resource": r.name, "type": r.type, **handler(r)})
    return out
