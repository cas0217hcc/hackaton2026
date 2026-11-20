"""Products worker + notifier (Azure Functions, Python v2 programming model, Flex Consumption).

apply_command : Storage Queue "products" -> Cosmos DB
                  upsert -> write the product document; with previousCategory (a category
                            change) the new partition is written FIRST, then the old document
                            is soft-deleted with movedTo - one command, so no half-done moves
                  delete -> soft delete: mark deleted + short ttl, so the change feed sees it
                            and Cosmos TTL purges it afterwards; the product image is removed
                ordering : every command carries requestedAt; commands older than the stored
                           document are skipped, and writes use etag checks (optimistic
                           concurrency), so delayed retries can't overwrite newer data
                - transient failure -> re-enqueue a copy with a visibility timeout
                                       (= scheduled retry with exponential backoff)
                - permanent failure -> raise; the runtime retries up to maxDequeueCount
                                       (host.json), then moves it to "products-poison" (our DLQ)
notify_products : Cosmos DB change feed on the products container -> notification
                  (logged; optionally POSTed to NOTIFY_WEBHOOK_URL)

All bindings and SDK clients authenticate with the app's user-assigned managed identity.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone

import azure.functions as func
from azure.core import MatchConditions
from azure.core.exceptions import ResourceNotFoundError
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.storage.blob import BlobServiceClient
from azure.storage.queue import QueueClient

app = func.FunctionApp()
log = logging.getLogger("products-worker")

MAX_SCHEDULED_RETRIES = int(os.getenv("MAX_SCHEDULED_RETRIES", "3"))
RETRY_BASE_SECONDS = int(os.getenv("RETRY_BASE_SECONDS", "10"))
DELETED_TTL_SECONDS = int(os.getenv("DELETED_TTL_SECONDS", "60"))
TRANSIENT_STATUS = {408, 429, 449, 500, 503}


class TransientError(Exception):
    pass


class PermanentError(Exception):
    pass


# ---------- lazily created clients (reused across invocations) ----------
_credential = None
_products = None
_queue = None
_images = None


def credential():
    global _credential
    if _credential is None:
        client_id = os.getenv("AZURE_CLIENT_ID")
        _credential = ManagedIdentityCredential(client_id=client_id) if client_id else DefaultAzureCredential()
    return _credential


def products_container():
    global _products
    if _products is None:
        cosmos = CosmosClient(os.environ["COSMOS_ENDPOINT"], credential=credential())
        _products = cosmos.get_database_client(os.environ["COSMOS_DATABASE"]).get_container_client(
            os.environ["COSMOS_CONTAINER"]
        )
    return _products


def products_queue():
    global _queue
    if _queue is None:
        _queue = QueueClient(
            os.environ["ProductsQueue__queueServiceUri"], os.environ["PRODUCTS_QUEUE"], credential=credential()
        )
    return _queue


def images_container():
    global _images
    if _images is None:
        blob = BlobServiceClient(os.environ["STORAGE_BLOB_ENDPOINT"], credential=credential())
        _images = blob.get_container_client(os.environ["IMAGES_CONTAINER"])
    return _images


# ---------- worker ----------
def read_or_none(container, product_id: str, category: str) -> dict | None:
    try:
        return container.read_item(product_id, partition_key=category)
    except CosmosResourceNotFoundError:
        return None


def is_stale(existing: dict | None, requested_at: str) -> bool:
    # ISO-8601 UTC timestamps from the same generator compare correctly as strings.
    # Equal timestamps = the same command re-processed -> re-apply (idempotent).
    return existing is not None and existing.get("requestedAt", "") > requested_at


def write_guarded(container, existing: dict | None, doc: dict) -> None:
    """Optimistic concurrency: fail (-> retry and re-evaluate) if the document changed since we read it."""
    if existing is None:
        container.create_item(doc)  # 409 if a concurrent command created it first
    else:
        container.replace_item(
            existing["id"], doc, etag=existing["_etag"], match_condition=MatchConditions.IfNotModified
        )


def upsert_product(product: dict, requested_at: str) -> bool:
    container = products_container()
    existing = read_or_none(container, product["id"], product["category"])
    if is_stale(existing, requested_at):
        log.warning("Skipping stale upsert for %s (%s < %s)", product["id"], requested_at, existing["requestedAt"])
        return False
    doc = {k: v for k, v in product.items() if k != "ttlSeconds"}  # fresh doc: clears deleted/ttl/movedTo
    doc["requestedAt"] = requested_at
    doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
    if product.get("ttlSeconds"):
        doc["ttl"] = int(product["ttlSeconds"])  # per-item TTL overrides the container default
    write_guarded(container, existing, doc)
    return True


def soft_delete(product_id: str, category: str, requested_at: str, moved_to: str | None = None) -> bool:
    """Returns False if the command is stale (a newer write exists) and must not take effect."""
    container = products_container()
    existing = read_or_none(container, product_id, category)
    if existing is None:
        log.info("Product %s/%s already gone", category, product_id)
        return True
    if is_stale(existing, requested_at):
        log.warning("Skipping stale delete for %s (%s < %s)", product_id, requested_at, existing["requestedAt"])
        return False
    if existing.get("deleted"):
        return True
    doc = {k: v for k, v in existing.items() if not k.startswith("_")}
    doc.update(
        {
            "deleted": True,
            "deletedAt": datetime.now(timezone.utc).isoformat(),
            "requestedAt": requested_at,
            "ttl": DELETED_TTL_SECONDS,
        }
    )
    if moved_to:
        doc["movedTo"] = moved_to  # lets the notifier tell a move from a real delete
    write_guarded(container, existing, doc)
    return True


def delete_image(product_id: str) -> None:
    try:
        images_container().delete_blob(product_id)
        log.info("Deleted image for product %s", product_id)
    except ResourceNotFoundError:
        pass


def apply(command: dict, retry_count: int) -> None:
    action = command.get("action")
    product = command.get("product") or {}
    if action not in ("upsert", "delete") or not product.get("id") or not product.get("category"):
        raise PermanentError("command needs action upsert|delete and product.id + product.category")

    simulate = command.get("simulate", "none")
    if simulate == "poison":
        raise PermanentError("simulated poison message")
    if simulate == "transient" and retry_count < 2:
        raise TransientError(f"simulated transient failure (attempt {retry_count + 1})")

    requested_at = command.get("requestedAt") or datetime.now(timezone.utc).isoformat()
    try:
        if action == "upsert":
            written = upsert_product(product, requested_at)
            previous = command.get("previousCategory")
            if written and previous and previous != product["category"]:
                # new partition is written; now retire the old document (safe to retry)
                soft_delete(product["id"], previous, requested_at, moved_to=product["category"])
        else:
            if soft_delete(product["id"], product["category"], requested_at):
                delete_image(product["id"])
    except (CosmosAccessConditionFailedError, CosmosResourceExistsError) as e:
        # a concurrent command changed the document - retry; the stale check re-evaluates
        raise TransientError(f"concurrent update on {product['id']}: {e.status_code}") from e
    except CosmosHttpResponseError as e:
        if e.status_code in TRANSIENT_STATUS:
            raise TransientError(f"Cosmos DB returned {e.status_code}") from e
        raise


def schedule_retry(command: dict, retry_count: int) -> None:
    delay = RETRY_BASE_SECONDS * (2**retry_count)  # 10s, 20s, 40s ...
    retry = {**command, "retryCount": retry_count + 1}
    # visibility_timeout hides the message until the delay has passed (max 7 days)
    products_queue().send_message(json.dumps(retry), visibility_timeout=delay)
    log.warning("Scheduled retry %d for product %s in %ss", retry_count + 1, command["product"]["id"], delay)


@app.queue_trigger(arg_name="msg", queue_name="%PRODUCTS_QUEUE%", connection="ProductsQueue")
def apply_command(msg: func.QueueMessage) -> None:
    raw = msg.get_body().decode("utf-8")
    log.info("Received queue message %s (dequeueCount=%s)", msg.id, msg.dequeue_count)
    retry_count = 0

    try:
        command = json.loads(raw)
        retry_count = int(command.get("retryCount", 0))
        apply(command, retry_count)
        log.info("Applied %s for product %s (retryCount=%d)", command["action"], command["product"]["id"], retry_count)
    except TransientError as e:
        if retry_count < MAX_SCHEDULED_RETRIES:
            log.warning("Transient failure for message %s: %s", msg.id, e)
            schedule_retry(command, retry_count)
            return  # original is deleted; the delayed copy carries on
        log.error("Scheduled retries exhausted for message %s: %s", msg.id, e)
        raise  # -> runtime retries -> products-poison
    except (PermanentError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        log.error("Permanent failure for message %s: %s (dequeue %s)", msg.id, e, msg.dequeue_count)
        raise  # -> runtime retries up to maxDequeueCount -> products-poison


# ---------- notifier (change feed) ----------
@app.cosmos_db_trigger(
    arg_name="docs",
    connection="CosmosDBConnection",
    database_name="%COSMOS_DATABASE%",
    container_name="%COSMOS_CONTAINER%",
    lease_container_name="leases",
    create_lease_container_if_not_exists=False,
)
def notify_products(docs: func.DocumentList) -> None:
    webhook = os.getenv("NOTIFY_WEBHOOK_URL")
    for doc in docs:
        if doc.get("deleted") and doc.get("movedTo"):
            continue  # old copy of a moved product; the new partition emits ProductUpserted
        note = {
            "event": "ProductDeleted" if doc.get("deleted") else "ProductUpserted",
            "id": doc.get("id"),
            "name": doc.get("name"),
            "category": doc.get("category"),
            "price": doc.get("price"),
            "stock": doc.get("stock"),
            "at": doc.get("deletedAt") or doc.get("updatedAt"),
        }
        log.info("NOTIFY %s", json.dumps(note))
        if webhook:
            try:
                req = urllib.request.Request(
                    webhook,
                    data=json.dumps(note).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=5).close()
            except Exception as e:  # notification is best-effort
                log.warning("Webhook failed for %s: %s", note["id"], e)
