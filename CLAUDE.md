# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project goal

Hackathon project (Hackathon Portugal 2026, InfraHack). It has two parts: a small Azure workload (`demo_app/`) and a migration tool (`migration_assistant/`) that reads an Azure resource group, shows each resource with its configuration, assesses how it maps to Leaseweb, runs the direct migrations (dry run by default, live with a Leaseweb API key) and, for resources with no Leaseweb equivalent, has an AI propose a Leaseweb setup plus the application code changes. `README.md` is the user-facing description; the design and plan are in `docs/superpowers/`.

## Layout

- `migration_assistant/` is the tool: a FastAPI app with a plain HTML, CSS and JavaScript UI (no build step). One module per stage: `azure_discovery.py` (Discover), `assess.py` (routing rules), `plan.py` (AI plans, parallel), `dryrun.py` (ordered, prefilled Leaseweb calls, the dry-run and live executors, teardown and the curl export), `diffcheck.py` (`git apply --check` on AI diffs), `cloudinit.py` (userData for rebuilt services), `costs.py` (price estimate), `datamove.py` (data copy commands), `leaseweb_ops.py` (reads the OpenAPI specs), `llm.py` and `claude_cli.py` (AI providers: Claude Code CLI, Anthropic API, opencode), `mock/` (mock mode: `MOCK_AZURE`, `MOCK_AI` and `MOCK_LEASEWEB` each mock one part, `MOCK_MODE` all three; one module per part: `azure.py` reads `mock_data/hackaton-2026-rg.json`, a scrubbed copy of the real group, rebuilt with `scripts/make_mock_fixture.py`; `ai.py` answers each `prompt.Prompt` task; `leaseweb.py` is a fake Leaseweb API that routes by the specs, keeps what it creates in memory and answers with the spec examples), `envfile.py` (reads `.env` in the repo root at startup; the environment wins; see `.env.example`), `app.py` (routes, saved state, in-memory keys).
- `tests/` has the tests for it. `sample_app/` is a tiny app used as a code-analysis input. `start.sh`, `start.ps1` and `start.bat` start the server.
- `demo_app/` is the source workload on Azure. `demo_app/README.md` has the API table, security model and deploy details.
- `leaseweb-api/` is a vendored copy of the official Leaseweb OpenAPI definitions (publicCloud, privateNetworks, objectStorage). It holds `openapi.yaml` plus `paths/` and `components/` linked by `$ref`, and generated `code_samples/`. Treat it as read-only reference. The auth header is `X-LSW-Auth`.

## migration_assistant: commands and conventions

- Run: `./start.sh` (Linux and macOS) or `start.bat` (Windows). Tests: `python3 -m pytest` from the repo root. Add `--reload` to the start script while developing, because the server does not pick up new routes otherwise.
- Every Leaseweb operation the app shows or sends must exist in `leaseweb-api/` (`leaseweb_ops.py` reads the specs). An operation an AI invents is dropped. Calls still holding a placeholder value are never sent.
- Non-GET requests with a foreign `Origin`, and any request whose `Host` is not localhost, an IP or in `ALLOWED_HOSTS`, are refused (middleware in `app.py`): the app can send live calls, so keep that check.
- Prerequisites are enforced in both places: the UI disables Discover without an Azure sign-in and Generate plan without a ready AI provider, and `/api/plan` returns 409 when the built-in provider is not available. `azure_status_fn` and `subscriptions_fn` are injectable like the other I/O.
- Secrets (the Leaseweb key and the Anthropic key) live in server memory only. They must never be saved to `data/state.json`, returned by an endpoint or put in an export. Saved results go to `data/state.json` (git-ignored).
- Every AI request is a `prompt.Prompt` (the text plus a `task` and its inputs). A new kind of request needs a task in `prompt.TASKS` and an answer in `mock/ai.py`; a test fails otherwise. Mock mode is wired only through `mock_overrides()` and neutral `create_app` options (`notice`, `ai_providers`, `api_key`, `settings_file`); a preset `api_key` is refused unless the HTTP client is fake. Nothing in `mock/` reads the environment: `_app_from_env` passes the switches and `MOCK_DELAY` in. The Azure subscription is kept in `data/settings.json`, shared by real and mock runs.
- The `az` runner, the AI function and the HTTP client are injected into the modules, so tests run with fakes and without Azure, an AI or Leaseweb. Keep new I/O injectable.
- The UI is plain JavaScript in `static/`. `diff.js` is pure (loadable from Node) and has Node-based tests; a test guards `app.js` against duplicate function names, which silently override each other in the browser.
- The project is Apache-2.0 (`LICENSE`). Third-party assets (Azure icons, the Leaseweb logo) keep their own terms and are listed in `NOTICE`.

## demo_app architecture

The write path is asynchronous, so understanding it takes more than one file:

- `api/app/main.py` is a FastAPI service on Azure Container Apps. GET reads Cosmos DB directly. POST, PUT and DELETE only enqueue a command on the Storage Queue `products` and return `202`. Writes need an `X-API-Key` header, and the key is read from Key Vault.
- `worker/function_app.py` is an Azure Functions app (Python v2, Flex Consumption). `apply_command` consumes the queue and writes to Cosmos DB. `notify_products` is the Cosmos change feed trigger.
- `?simulate=transient|poison` on write endpoints exercises the failure paths. Transient failures re-enqueue with a growing visibility timeout. Poison messages move to `products-poison` after 3 dequeues.
- Deletes are soft deletes, and TTL then purges the item. The Cosmos container is partitioned on `/category`.
- Everything authenticates with user-assigned managed identities and RBAC. There are no connection strings, and Cosmos key auth is disabled. Adding a new dependency to the API or worker means adding the matching role assignment in `infra/`.
- `infra/` is Terraform (azurerm 4.x). The Container App is created only when `var.api_image` is non-empty, which is why deploy is two-phase. Every resource carries a `component` tag and `workload=products-demo`, which the migration tool is meant to use for discovery.

## demo_app commands

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
