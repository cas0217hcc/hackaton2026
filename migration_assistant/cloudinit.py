"""Starting-point cloud-init for the Public Cloud instance that hosts a rebuilt service.

Sent as `userData` with launchInstance (plain text, as the spec asks). Each script installs the
service from its vendor's apt repository on Ubuntu 22.04 and leaves configuration to the operator:
review it before a live run.
"""

HEAD = "#cloud-config\npackage_update: true\npackages: [curl, gnupg, ca-certificates, lsb-release]\nruncmd:\n"


def _script(lines: list[str]) -> str:
    return HEAD + "".join(f"  - {line}\n" for line in lines)


VAULT = _script([
    "curl -fsSL https://apt.releases.hashicorp.com/gpg | gpg --dearmor -o /usr/share/keyrings/hashicorp.gpg",
    "echo \"deb [signed-by=/usr/share/keyrings/hashicorp.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main\" > /etc/apt/sources.list.d/hashicorp.list",
    "apt-get update && apt-get install -y vault",
    "systemctl enable --now vault",
])

MONGODB = _script([
    "curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | gpg --dearmor -o /usr/share/keyrings/mongodb-7.0.gpg",
    "echo \"deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-7.0.gpg] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse\" > /etc/apt/sources.list.d/mongodb-org-7.0.list",
    "apt-get update && apt-get install -y mongodb-org",
    "systemctl enable --now mongod",
])

RABBITMQ = _script([
    "apt-get install -y rabbitmq-server",
    "systemctl enable --now rabbitmq-server",
])

POSTGRES = _script([
    "apt-get install -y postgresql",
    "systemctl enable --now postgresql",
])

MONITORING = _script([
    "mkdir -p /etc/apt/keyrings",
    "curl -fsSL https://apt.grafana.com/gpg.key | gpg --dearmor -o /etc/apt/keyrings/grafana.gpg",
    "echo \"deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main\" > /etc/apt/sources.list.d/grafana.list",
    "apt-get update && apt-get install -y grafana loki prometheus",
    "systemctl enable --now grafana-server loki prometheus",
])

APP = _script([
    "apt-get install -y python3 python3-venv python3-pip nginx",
    "systemctl enable --now nginx",
])

# First keyword found in the assessment target (lower case) wins.
BY_KEYWORD = [("vault", VAULT), ("mongo", MONGODB), ("rabbitmq", RABBITMQ), ("grafana", MONITORING),
              ("database", POSTGRES), ("postgres", POSTGRES), ("app", APP)]


def user_data_for(target: str) -> str | None:
    """cloud-init for an assessment target such as 'HashiCorp Vault on a Public Cloud instance', or None."""
    t = (target or "").lower()
    for word, script in BY_KEYWORD:
        if word in t:
            return script
    return None
