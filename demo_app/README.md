# Products demo app (Azure) - source workload for the Leaseweb migration

```
Client ─► Container App (Products API) ──► Storage Queue "products" ──► Function (worker)
              │   GET  → Cosmos DB (read)        │ poison queue,                │
              │   POST/PUT/DELETE → queue (202)  │ delayed retry                ▼
              ├─► Blob "product-images"          │ (visibility timeout)   Cosmos DB (NoSQL API,
              └─► Key Vault (API key) via Managed Identity                partition /category,
                                                                          TTL, change feed → notifier)
```

| Folder | What |
|---|---|
| `api/` | FastAPI Products API, container image for Azure Container Apps |
| `worker/` | Azure Functions (Python v2, Flex Consumption): `apply_command` (queue → Cosmos) and `notify_products` (change feed) |
| `infra/` | Terraform (azurerm 4.x): everything above, plus ACR, Log Analytics and App Insights |
| `scripts/` | `deploy.ps1` (end-to-end deploy), `demo.ps1` (scripted walkthrough) |

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/products?category=` | list (single-partition query when `category` is given) |
| GET | `/products/{id}` | read |
| POST | `/products` | **X-API-Key**. Queued, returns `202` + id |
| PUT | `/products/{id}` | **X-API-Key**. Queued, update-only (404 if missing). A category change is a move, done as one command |
| DELETE | `/products/{id}` | **X-API-Key**. Queued soft delete |
| PUT / GET | `/products/{id}/image` | upload (raw bytes, `Content-Type: image/*`) / download from Blob |
| GET | `/docs` | Swagger UI |

Write endpoints accept `?simulate=transient|poison` to show the failure paths live:

- **transient**: the worker fails, re-enqueues the command with a visibility timeout (10s, 20s, ...) and then succeeds.
- **poison**: the runtime retries 3× (`maxDequeueCount`) and then moves the message to `products-poison`.

Product body: `{"name": "VPS Small", "category": "compute", "price": 9.99, "stock": 100, "ttlSeconds": 120}`. `ttlSeconds` is optional and sets a per-item TTL.

## Security model

- **No connection strings or keys in app config.** The API and the worker each have a user-assigned managed identity with least-privilege RBAC: Blob/Queue data roles, Key Vault Secrets User, AcrPull and Cosmos data-plane roles.
- Cosmos DB has local (key) auth **disabled**. Key Vault uses RBAC.
- The only secret is the API key (`products-api-key` in Key Vault). Terraform generates it, so it is also stored in Terraform state: keep state private.

## Deploy

Prerequisites: Terraform ≥ 1.9, Azure CLI, and `az login` with rights to create resources and role assignments (Owner, or Contributor + User Access Administrator) on the resource group.

```powershell
# values from infra/terraform.tfvars (copy from terraform.tfvars.example; git-ignored)
./scripts/deploy.ps1

# or explicitly, against an existing resource group (parameters override terraform.tfvars)
./scripts/deploy.ps1 -SubscriptionId <subscription-guid> -ResourceGroup <rg-name>

# or let Terraform create it
./scripts/deploy.ps1 -SubscriptionId <guid> -ResourceGroup rg-products-demo -CreateResourceGroup -Location westeurope
```

The script runs `terraform plan` and waits for `yes` before applying. Then it:

1. builds the API image with `az acr build` (no local Docker needed),
2. creates the Container App with that image,
3. zip-deploys the Function app code.

To run Terraform by hand: copy `infra/terraform.tfvars.example` to `terraform.tfvars`, then run `terraform init/plan/apply` inside `infra/`. The Container App is only created when `api_image` is set.

```powershell
./scripts/demo.ps1          # walkthrough (reads API URL + key from terraform output / Key Vault)
terraform -chdir=infra destroy -var=subscription_id=... -var=resource_group_name=...
```

## Migration notes (for the Leaseweb mapping)

Every resource has a `component` tag (`api`, `worker`, `app-storage`, `database`, `secrets`, ...) and `workload=products-demo`, so the migration tool can discover and map them.
