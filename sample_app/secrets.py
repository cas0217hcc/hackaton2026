"""Stand-in demo app: reads the database password from Azure Key Vault."""
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

VAULT_URL = "https://kv-hack-b4e3bc40.vault.azure.net"


def get_db_password() -> str:
    client = SecretClient(vault_url=VAULT_URL, credential=DefaultAzureCredential())
    return client.get_secret("db-password").value
