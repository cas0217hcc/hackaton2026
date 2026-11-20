# Azure to Leaseweb Migration Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local Python web app that reads an Azure resource group, classifies each resource as Direct or Rebuild for Leaseweb, dry-runs the migration of Direct resources, and for Rebuild resources proposes an infra replacement plus code changes.

**Architecture:** A small FastAPI app drives a four-stage flow (Discover, Assess, Plan, Migrate). Each stage is a plain Python module with injectable I/O (`az` runner, `claude` runner, executor) so tests use fakes. Leaseweb operation names are read from the OpenAPI specs in `leaseweb-api/` and every operation the app emits is validated against that index.

**Tech Stack:** Python 3.10 (installed version), FastAPI, Jinja2, uvicorn, PyYAML, pytest. `az` CLI and `claude` CLI (both on PATH) are called as subprocesses.

**Spec:** `docs/superpowers/specs/2026-11-20-azure-to-leaseweb-migration-assistant-design.md`

## Global Constraints

- Language: Python. Local only; no auth, hosting or multi-user support.
- Azure is read-only: only `az ... list/show` style commands. Subscription "GDC - Sandbox", resource group `hackaton-2026-rg` (default value, editable in the UI).
- AI calls go through `claude -p` as a subprocess. No Anthropic API key and no SDK. Live calls only, no cached fallback; failures show a clear error and allow retry.
- Migrate is dry-run only. The executor sits behind an interface whose default implementation sends nothing.
- Every Leaseweb operation shown to the user must exist as an `operationId` in `leaseweb-api/{publicCloud,objectStorage,privateNetworks}`. Where the specs and the expected "VM, networking, storage are Direct" disagree, the specs win.
- UI is the guided flow (layout A): stages Discover, Assess, Plan, Migrate; restrained palette, system sans, monospace only for resource IDs, status pills Direct / Rebuild; Plan has an Export plan action.
- Source code input is a local folder path typed into the browser; Python is the only supported source language.

## Review Focus

- `hackaton-2026-rg` empty or `az` not logged in: show a clear error on Discover, not a stack trace. (Task 2)
- `claude -p` times out, exits non-zero, or returns non-JSON/fenced JSON: raise `ClaudeError`, UI shows message and a retry control. (Task 3)
- Source folder path missing, empty, or containing no `.py` files: Plan still produces the infra proposal and reports "no code to analyse". (Task 5)
- Claude proposes an operationId not in the specs: it is dropped and a warning is attached to the plan. (Task 5)
- Every resource is Direct (nothing to plan): Plan stage says so instead of showing an empty page. (Task 7)

---

## File Structure

- `migration_assistant/models.py`: dataclasses shared by all stages.
- `migration_assistant/leaseweb_ops.py`: operation index from the OpenAPI specs.
- `migration_assistant/azure_discovery.py`: Discover stage.
- `migration_assistant/claude_cli.py`: `claude -p` wrapper.
- `migration_assistant/assess.py`: rules table and Claude fallback.
- `migration_assistant/plan.py`: infra proposal and code analysis.
- `migration_assistant/dryrun.py`: executor interface and dry-run call builder.
- `migration_assistant/app.py` and `migration_assistant/templates/`: web UI.
- `sample_app/`: stand-in Python app (Key Vault and Blob SDK calls) for demo and tests.
- `tests/`: one test module per module above.

### Task 1: Models and Leaseweb operation index

**Files:**
- Create: `migration_assistant/__init__.py`, `migration_assistant/models.py`, `migration_assistant/leaseweb_ops.py`, `requirements.txt`
- Test: `tests/test_leaseweb_ops.py`

**Interfaces:**
- Produces (`models.py`): `Resource(id: str, name: str, type: str, location: str, properties: dict)`, `Assessment(resource_name: str, route: Literal["direct","rebuild"], target: str, rationale: str, lw_operations: list[str])`, `CodeChange(file: str, summary: str, diff: str)`, `Plan(resource_name: str, proposal: str, lw_operations: list[str], code_changes: list[CodeChange], warnings: list[str])`, `DryRunCall(method: str, path: str, operation_id: str, body: dict)`. All `@dataclass`.
- Produces (`leaseweb_ops.py`): `load_operations(specs_dir: Path = Path("leaseweb-api")) -> dict[str, tuple[str, str]]` mapping operationId to (HTTP method, path), covering the three spec folders.

- [ ] **Step 1: Write failing tests** in `tests/test_leaseweb_ops.py`: `test_known_operations_present` asserts `createObjectStorageBucket`, `createSecurityGroup`, `getInstanceList` are keys; `test_operation_has_method_and_path` asserts `load_operations()["createObjectStorageBucket"][0] == "POST"` and its path starts with `/objectStorage/v1/`.
- [ ] **Step 2: Run** `pytest tests/test_leaseweb_ops.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the dataclasses and `load_operations`. Resolve method and path by joining each path file's operations to the `$ref` entries in the folder's `openapi.yaml`. List dependencies in `requirements.txt`.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: models and leaseweb operation index`.

### Task 2: Azure discovery

**Files:**
- Create: `migration_assistant/azure_discovery.py`
- Test: `tests/test_azure_discovery.py`

**Interfaces:**
- Consumes: `Resource` from Task 1.
- Produces: `list_resources(resource_group: str, runner: Callable = subprocess.run) -> list[Resource]`; raises `DiscoveryError(message: str)` on non-zero exit or empty group.

- [ ] **Step 1: Write failing tests** with a fake runner returning `az resource list` JSON: `test_parses_resources` (two entries become two `Resource`s with `type == "Microsoft.KeyVault/vaults"` for the vault), `test_az_failure_raises` (exit code 1 with stderr "Please run 'az login'" raises `DiscoveryError` containing that text), `test_empty_group_raises`.
- [ ] **Step 2: Run** `pytest tests/test_azure_discovery.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `list_resources` calling `az resource list -g <rg> -o json`.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: azure resource discovery`.

### Task 3: Claude CLI wrapper

**Files:**
- Create: `migration_assistant/claude_cli.py`
- Test: `tests/test_claude_cli.py`

**Interfaces:**
- Produces: `ask_json(prompt: str, timeout: int = 180, runner: Callable = subprocess.run) -> dict`; raises `ClaudeError(message: str)` on timeout, non-zero exit, or unparseable output. Accepts JSON wrapped in a markdown code fence.

- [ ] **Step 1: Write failing tests** with a fake runner: `test_plain_json`, `test_fenced_json` (output "```json\n{\"a\": 1}\n```" returns `{"a": 1}`), `test_non_json_raises`, `test_timeout_raises` (runner raises `subprocess.TimeoutExpired`), `test_nonzero_exit_raises`.
- [ ] **Step 2: Run** `pytest tests/test_claude_cli.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `ask_json` invoking `claude -p <prompt>`; the prompt tells Claude to answer with JSON only.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: claude cli wrapper`.

### Task 4: Assessment

**Files:**
- Create: `migration_assistant/assess.py`
- Test: `tests/test_assess.py`

**Interfaces:**
- Consumes: `Resource`, `Assessment`, `load_operations`, `ask_json`.
- Produces: `assess(resources: list[Resource], ask: Callable = ask_json, ops: dict | None = None) -> list[Assessment]`.

Rules table keyed by Azure type. Starting points, each validated against the operation index by test: `Microsoft.Compute/virtualMachines` Direct (Public Cloud instance), `Microsoft.Network/networkSecurityGroups` Direct (security group), `Microsoft.Storage/storageAccounts` Direct (Object Storage bucket), `Microsoft.Network/publicIPAddresses` Direct (instance IP), `Microsoft.KeyVault/vaults` Rebuild (Vault on a Public Cloud instance), plus Rebuild for Functions, Cosmos DB, Service Bus, Azure SQL. NICs and OS disks are folded into their VM and do not appear as rows. `Microsoft.Network/virtualNetworks` is the builder's call: Direct only if the private-network specs contain a create operation, otherwise Rebuild. Unknown types go to `ask`.

- [ ] **Step 1: Write failing tests**: `test_vm_is_direct`, `test_keyvault_is_rebuild`, `test_every_rule_operation_exists_in_specs` (all `lw_operations` in the rules table are keys of `load_operations()`), `test_nic_and_disk_not_listed`, `test_unknown_type_uses_claude` (fake `ask` returns a Rebuild verdict for `Microsoft.Foo/bars`).
- [ ] **Step 2: Run** `pytest tests/test_assess.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `assess` with the rules table; unknown types are classified by one `ask` call per type.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: assess azure resources for leaseweb fit`.

### Task 5: Plan stage (infra proposal and code changes)

**Files:**
- Create: `migration_assistant/plan.py`
- Test: `tests/test_plan.py`

**Interfaces:**
- Consumes: `Assessment`, `Resource`, `Plan`, `CodeChange`, `ask_json`, `load_operations`.
- Produces: `read_source(source_dir: Path | None, max_bytes: int = 200_000) -> dict[str, str]` (relative path to text, `.py` files only, empty dict if folder missing or has none); `build_plan(assessment: Assessment, resource: Resource, source: dict[str, str], ask: Callable = ask_json, ops: dict | None = None) -> Plan`.

The prompt includes the resource, the Rebuild rationale, the source files (if any) and the list of valid Leaseweb operationIds. Expected Claude JSON shape: `{"proposal": str, "lw_operations": [str], "code_changes": [{"file": str, "summary": str, "diff": str}]}`.

- [ ] **Step 1: Write failing tests**: `test_read_source_python_only`, `test_read_source_missing_folder_returns_empty`, `test_plan_without_source_has_no_code_changes_and_notes_it` (warnings contains "no code to analyse"), `test_unknown_operation_dropped_with_warning` (fake `ask` returns `lw_operations: ["createObjectStorageBucket", "launchQuantumVault"]`; plan keeps the first, warnings mention the second), `test_code_changes_parsed`.
- [ ] **Step 2: Run** `pytest tests/test_plan.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `read_source` and `build_plan`.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: plan stage with code-change analysis`.

### Task 6: Dry-run executor

**Files:**
- Create: `migration_assistant/dryrun.py`
- Test: `tests/test_dryrun.py`

**Interfaces:**
- Consumes: `Assessment`, `DryRunCall`, `load_operations`.
- Produces: `build_calls(assessments: list[Assessment], ops: dict | None = None) -> list[DryRunCall]` (Direct resources only, placeholder or spec-default body values); `class Executor(Protocol): def execute(self, call: DryRunCall) -> dict`; `class DryRunExecutor` implementing it, sending nothing and returning `{"dry_run": True, "sent": False, ...}`.

- [ ] **Step 1: Write failing tests**: `test_rebuild_resources_excluded`, `test_calls_use_spec_method_and_path` (a bucket call has method POST and path under `/objectStorage/v1/`), `test_dry_run_executor_sends_nothing` (no network access: monkeypatch `socket.socket` to raise, `execute` still returns `sent: False`).
- [ ] **Step 2: Run** `pytest tests/test_dryrun.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the builder and `DryRunExecutor`.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: dry-run migration executor`.

### Task 7: Web app

**Files:**
- Create: `migration_assistant/app.py`, `migration_assistant/templates/index.html`, `migration_assistant/static/style.css`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: all earlier modules.
- Produces: FastAPI `app` with `POST /api/discover` (form: `resource_group`), `POST /api/assess`, `POST /api/plan` (form: `source_dir`, optional), `POST /api/migrate`, `GET /export` (Markdown of assessments, plans and dry-run calls). In-memory state for the single session. Errors return JSON `{"error": str}` with status 502 for `ClaudeError`/`DiscoveryError`. Page: four-stage stepper per the mockup `.superpowers/brainstorm/88477-1795168248/content/layout-v2.html` (option A), loading and retry states for slow `claude` calls.

- [ ] **Step 1: Write failing tests** with FastAPI `TestClient` and dependency overrides for fake discovery/claude: `test_full_flow` (discover, assess, plan, migrate each return 200 and `/export` contains "kv-hack"), `test_discover_error_returns_502_message`, `test_plan_when_all_direct_says_nothing_to_plan`, `test_claude_error_returns_502_message`.
- [ ] **Step 2: Run** `pytest tests/test_app.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** routes and the page. Follow the visual rules in Global Constraints; run `impeccable detect` on the template when done.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: web ui for guided migration flow`.

### Task 8: Stand-in sample app and end-to-end check

**Files:**
- Create: `sample_app/secrets.py`, `sample_app/storage.py` (small Python module using `azure-keyvault-secrets` and `azure-storage-blob` calls), `README.md` (run instructions)
- Test: `tests/test_sample_app_fixture.py`

**Interfaces:**
- Consumes: `read_source`.

- [ ] **Step 1: Write failing test**: `test_read_source_finds_sample_app` asserts `read_source(Path("sample_app"))` contains both files and that `secrets.py` text includes `SecretClient`.
- [ ] **Step 2: Run** `pytest tests/test_sample_app_fixture.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the sample files.
- [ ] **Step 4: Run** the full suite `pytest -v`. Expected: all PASS.
- [ ] **Step 5: Manual demo check**: `uvicorn migration_assistant.app:app`, open the page, run all four stages on `hackaton-2026-rg` with `sample_app/` as source. Expected: Key Vault shows Rebuild with Vault proposal and a diff touching `sample_app/secrets.py`; Migrate shows dry-run calls only.
- [ ] **Step 6: Commit** `feat: sample app and demo instructions`.
