"""Products API (Azure Container App).

Reads  : GET  /products, /products/{id}            -> Cosmos DB (direct)
Writes : POST /products, PUT/DELETE /products/{id} -> command on Storage Queue "products"
         (202 Accepted). The Function worker applies it to Cosmos DB.
Images : PUT/GET /products/{id}/image              -> Blob Storage "product-images"
UI     : the React app (built into ./static by the Dockerfile) is served at / when present.
Auth   : write endpoints need header X-API-Key; the key is read from Key Vault at startup.

All Azure access uses the Container App's user-assigned managed identity
(DefaultAzureCredential picks it up via AZURE_CLIENT_ID). Locally, `az login` works too.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Optional

from azure.core.exceptions import ResourceNotFoundError
from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.storage.queue import QueueClient
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

log = logging.getLogger("products-api")
logging.basicConfig(level=logging.INFO)

if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(logger_name="products-api")

MAX_IMAGE_BYTES = 5 * 1024 * 1024
Simulate = Literal["none", "transient", "poison"]


def env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


class Clients:
    def __init__(self) -> None:
        cred = DefaultAzureCredential()

        # Plain-text messages; the worker's host.json sets queues.messageEncoding = "none".
        self.queue = QueueClient(env("STORAGE_QUEUE_ENDPOINT"), env("PRODUCTS_QUEUE"), credential=cred)

        blob = BlobServiceClient(env("STORAGE_BLOB_ENDPOINT"), credential=cred)
        self.images = blob.get_container_client(env("IMAGES_CONTAINER"))

        cosmos = CosmosClient(env("COSMOS_ENDPOINT"), credential=cred)
        self.products = cosmos.get_database_client(env("COSMOS_DATABASE")).get_container_client(
            env("COSMOS_CONTAINER")
        )

        secret_name = os.getenv("API_KEY_SECRET_NAME", "products-api-key")
        self.api_key = SecretClient(env("KEYVAULT_URI"), cred).get_secret(secret_name).value
        log.info("Loaded API key '%s' from Key Vault", secret_name)

    def close(self) -> None:
        self.queue.close()


clients: Clients | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global clients
    clients = Clients()
    yield
    clients.close()


app = FastAPI(title="Products API", version="1.0.0", lifespan=lifespan)


# ---------- models ----------
class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")  # partition key
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    description: str = Field(default="", max_length=2000)
    stock: int = Field(default=0, ge=0)
    # Optional per-item TTL, e.g. a limited-time promo product that expires by itself.
    ttlSeconds: Optional[int] = Field(default=None, gt=0)


class Accepted(BaseModel):
    id: str
    action: str
    status: str = "accepted"
    location: str


# ---------- helpers ----------
def require_api_key(x_api_key: str = Header(default="")) -> None:
    # compare bytes: compare_digest raises TypeError on non-ASCII str input
    if not hmac.compare_digest(x_api_key.encode("utf-8"), clients.api_key.encode("utf-8")):
        raise HTTPException(401, "missing or invalid X-API-Key")


def strip_meta(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def find_product(product_id: str) -> dict | None:
    # Cross-partition lookup by id: fine for a demo-sized catalog.
    # (With the category known, use read_item(product_id, partition_key=category) instead.)
    items = list(
        clients.products.query_items(
            "SELECT * FROM c WHERE c.id = @id AND NOT IS_DEFINED(c.deleted) ORDER BY c.requestedAt DESC",
            parameters=[{"name": "@id", "value": product_id}],
            enable_cross_partition_query=True,
        )
    )
    return items[0] if items else None


def to_document(product_id: str, product: ProductIn) -> dict:
    doc = {"id": product_id, **product.model_dump(mode="json")}
    doc["price"] = float(product.price)  # store as a JSON number so queries/sorting work
    return doc


def enqueue(action: str, product: dict, simulate: Simulate, previous_category: str | None = None) -> None:
    command = {
        "action": action,  # "upsert" | "delete"
        "retryCount": 0,
        "simulate": simulate,  # demo switch for the worker's failure paths
        # the worker ignores commands older than what is already stored (ordering guard)
        "requestedAt": datetime.now(timezone.utc).isoformat(),
        "product": product,
    }
    if previous_category:
        command["previousCategory"] = previous_category  # category change = move, one command
    clients.queue.send_message(json.dumps(command))
    log.info("Queued %s for product %s", action, product["id"])


# ---------- endpoints ----------
@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/products")
def list_products(category: Optional[str] = None, limit: int = Query(default=50, ge=1, le=200)):
    query = "SELECT TOP @n * FROM c WHERE NOT IS_DEFINED(c.deleted) ORDER BY c.name"
    params = [{"name": "@n", "value": limit}]
    if category:  # single-partition query - cheapest path
        items = clients.products.query_items(query, parameters=params, partition_key=category)
    else:
        items = clients.products.query_items(query, parameters=params, enable_cross_partition_query=True)
    return [strip_meta(i) for i in items]


@app.get("/products/{product_id}")
def get_product(product_id: str):
    doc = find_product(product_id)
    if not doc:
        raise HTTPException(404, "product not found (or not processed yet)")
    return strip_meta(doc)


@app.post("/products", status_code=202, response_model=Accepted, dependencies=[Depends(require_api_key)])
def create_product(product: ProductIn, simulate: Simulate = "none"):
    product_id = str(uuid.uuid4())
    enqueue("upsert", to_document(product_id, product), simulate)
    return Accepted(id=product_id, action="create", location=f"/products/{product_id}")


@app.put(
    "/products/{product_id}", status_code=202, response_model=Accepted, dependencies=[Depends(require_api_key)]
)
def update_product(product_id: str, product: ProductIn, simulate: Simulate = "none"):
    """Update-only: 404 if the product doesn't exist (use POST to create)."""
    existing = find_product(product_id)
    if not existing:
        raise HTTPException(404, "product not found")
    # Category is the partition key: a change is a move, sent as ONE command so the worker
    # writes the new partition first and only then retires the old document.
    previous = existing["category"] if existing["category"] != product.category else None
    enqueue("upsert", to_document(product_id, product), simulate, previous_category=previous)
    return Accepted(id=product_id, action="update", location=f"/products/{product_id}")


@app.delete(
    "/products/{product_id}", status_code=202, response_model=Accepted, dependencies=[Depends(require_api_key)]
)
def delete_product(product_id: str, simulate: Simulate = "none"):
    existing = find_product(product_id)
    if not existing:
        raise HTTPException(404, "product not found")
    enqueue("delete", {"id": product_id, "category": existing["category"]}, simulate)
    return Accepted(id=product_id, action="delete", location=f"/products/{product_id}")


@app.put("/products/{product_id}/image", status_code=201, dependencies=[Depends(require_api_key)])
async def upload_image(product_id: str, request: Request):
    """Upload raw image bytes, e.g. curl -X PUT --data-binary @shoe.png -H 'Content-Type: image/png'."""
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        raise HTTPException(415, "Content-Type must be image/*")
    data = await request.body()
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, f"image must be 1 byte - {MAX_IMAGE_BYTES // 1024 // 1024} MB")
    if not find_product(product_id):
        raise HTTPException(404, "product not found")
    clients.images.upload_blob(
        product_id, data, overwrite=True, content_settings=ContentSettings(content_type=content_type)
    )
    return {"id": product_id, "image": f"/products/{product_id}/image", "bytes": len(data)}


@app.get("/products/{product_id}/image")
def get_image(product_id: str):
    if not find_product(product_id):
        raise HTTPException(404, "product not found")
    try:
        blob = clients.images.download_blob(product_id)
    except ResourceNotFoundError:
        raise HTTPException(404, "image not found")
    return Response(blob.readall(), media_type=blob.properties.content_settings.content_type)


# ---------- UI (React build, copied to /app/static by the Dockerfile) ----------
# Registered last so it never shadows an API route. The UI uses hash routing, so "/" is the only page URL.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if (STATIC_DIR / "index.html").is_file():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def ui_index():
        return FileResponse(STATIC_DIR / "index.html")
