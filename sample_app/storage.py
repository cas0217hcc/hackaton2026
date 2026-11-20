"""Stand-in demo app: uploads files to Azure Blob Storage."""
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

ACCOUNT_URL = "https://sthackb4e3bc40.blob.core.windows.net"


def upload(container: str, name: str, data: bytes) -> None:
    service = BlobServiceClient(ACCOUNT_URL, credential=DefaultAzureCredential())
    service.get_blob_client(container, name).upload_blob(data, overwrite=True)
