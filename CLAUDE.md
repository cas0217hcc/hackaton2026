# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project goal

Hackathon project: build a small Azure workload (`demo_app/`), then a migration tool that shows the Azure resources, proposes a mapping to Leaseweb, and executes the migration. The migration tool does not exist yet in this repo. `leaseweb-api/README.md` refers to a planned `hackaton2026/mapping/azure-leaseweb.yaml` (provisioners: instance, private_network, security_group, object_storage) and to a fake Leaseweb API derived from the OpenAPI specs, and neither is committed.

## Layout

- `demo_app/` is the source workload on Azure. `demo_app/README.md` has the API table, security model and deploy details.
- `leaseweb-api/` is a vendored copy of the official Leaseweb OpenAPI definitions (publicCloud, privateNetworks, objectStorage). It holds `openapi.yaml` plus `paths/` and `components/` linked by `$ref`, and generated `code_samples/`. Treat it as read-only reference. The auth header is `X-LSW-Auth`.

## demo_app architecture

The write path is asynchronous, so understanding it takes more than one file:

- `api/app/main.py` is a FastAPI service on Azure Container Apps. GET reads Cosmos DB directly. POST, PUT and DELETE only enqueue a command on the Storage Queue `products` and return `202`. Writes need an `X-API-Key` header, and the key is read from Key Vault.
- `worker/function_app.py` is an Azure Functions app (Python v2, Flex Consumption). `apply_command` consumes the queue and writes to Cosmos DB. `notify_products` is the Cosmos change feed trigger.
- `?simulate=transient|poison` on write endpoints exercises the failure paths. Transient failures re-enqueue with a growing visibility timeout. Poison messages move to `products-poison` after 3 dequeues.
- Deletes are soft deletes, and TTL then purges the item. The Cosmos container is partitioned on `/category`.
- Everything authenticates with user-assigned managed identities and RBAC. There are no connection strings, and Cosmos key auth is disabled. Adding a new dependency to the API or worker means adding the matching role assignment in `infra/`.
- `infra/` is Terraform (azurerm 4.x). The Container App is created only when `var.api_image` is non-empty, which is why deploy is two-phase. Every resource carries a `component` tag and `workload=products-demo`, which the migration tool is meant to use for discovery.

## Commands

All of these run from `demo_app/` in PowerShell, with Terraform >= 1.9 and an `az login` session:

```powershell
./scripts/deploy.ps1                        # plan, confirm "yes", apply infra, az acr build, apply Container App, zip-deploy the function
./scripts/deploy.ps1 -SubscriptionId <guid> -ResourceGroup <rg> [-CreateResourceGroup -Location westeurope] [-AutoApprove]
./scripts/demo.ps1                          # scripted walkthrough; reads API URL and key from terraform output and Key Vault
terraform -chdir=infra destroy -var=subscription_id=... -var=resource_group_name=...
```

- `deploy.ps1` takes subscription and resource group from parameters, or else from `infra/terraform.tfvars`. It never infers them from the az context. Copy `infra/terraform.tfvars.example` to create that file.
- There are no tests and no linter configured. `api/requirements.txt` and `worker/requirements.txt` are the only dependency manifests.
- `terraform.tfvars`, `*.tfstate` and `.terraform.lock.hcl` are git-ignored. `infra/` currently contains a local `terraform.tfstate`, which holds the generated API key, so do not commit or share it.
