# Azure to Leaseweb Migration Assistant

A local web tool that reads an Azure resource group, works out how each resource maps to [Leaseweb](https://www.leaseweb.com), migrates what maps directly, and plans what does not, including the application code changes that plan needs.

## Goal

Built at the Hackathon Portugal 2026 (InfraHack: AI for Cloud Infrastructure), for the challenge *sovereign alternatives for locked-in hyperscale services: can we replace some of them, keep a similar level of automation, and make migration easier?*

Moving a workload off a hyperscaler is mostly a series of decisions, not a copy: many Azure services (Key Vault, Functions, Cosmos DB, Service Bus and so on) have no Leaseweb equivalent. This tool aims to make that move easier:

- **Show** what is running in an Azure resource group and what each resource is configured with.
- **Decide** for each resource whether it maps directly, has to be rebuilt, or is part of another resource, using rules plus an AI for unknown types.
- **Automate** the direct part against the Leaseweb API, as a dry run first and live only when you choose.
- **Plan** the rest: for every resource with no equivalent, an AI proposes a Leaseweb setup, the exact API calls from the OpenAPI specs, and the application code changes it needs.

The AI never gets the last word on what can be called: every Leaseweb operation shown or sent must exist in the vendored OpenAPI specs.

## What it does

The app is a guided flow of four stages.

| Stage | What happens |
|---|---|
| **1. Discover** | Reads the resources of an Azure resource group with the `az` CLI, including each resource's configured values (VM size, SKU, address space and so on). Azure is only read, never changed. |
| **2. Assess** | Labels every resource **Direct** (maps cleanly to Leaseweb), **Rebuild** (no equivalent) or **Included** (part of another resource). It also finds which resources must exist before another can be created (see [Dependencies](#dependencies-between-resources)). The table can be filtered by route and searched. |
| **3. Manual migration** | For each Rebuild resource, an AI writes a Leaseweb infrastructure proposal with migration steps and the Leaseweb operations involved. If you give it source folders (up to 5), it also proposes code changes as diffs, for example replacing the Key Vault SDK with a Vault client. Each diff is checked with `git apply --check` against your source and marked **Applies cleanly** or **Does not apply**, and all of them download as one `.patch`. Plans are generated in parallel with a progress bar. |
| **4. Automatic migration** | Lists the Leaseweb API calls that migrate the Direct resources, plus the instance that hosts each Rebuild resource (with a starting-point cloud-init that installs Vault, MongoDB, RabbitMQ and so on), ordered by the dependencies found at Assess, with the values prefilled from what Discover found. It runs as a **dry run** by default. With a Leaseweb API key set, it sends the calls for real, and can remove what it created. Below the calls are a monthly compute cost estimate and the commands that copy the data itself. |

### How resources are classified

| Azure resource | Route | Leaseweb target |
|---|---|---|
| Virtual machine | Direct | Public Cloud instance (`launchInstance`) |
| Network security group | Direct | Security group and firewall rules |
| Storage account with blobs only | Direct | Object Storage bucket |
| Storage account with queues, tables or file shares | Rebuild | Object Storage for the blobs, plus RabbitMQ (for queues) or other services on an instance |
| Virtual network | Direct | Private network |
| Network interface, managed disk, public IP | Included | Part of their VM (or private endpoint); nothing to migrate separately |
| App Service plan | Included | Part of the app that runs on it |
| Managed identity | Included | Replaced by credentials stored in Vault |
| Private endpoint, private DNS zone and its links | Included | Part of the private network |
| Key Vault | Rebuild | HashiCorp Vault on a Public Cloud instance |
| App Service / Functions | Rebuild | App on a Public Cloud instance |
| Cosmos DB | Rebuild | Self-hosted MongoDB on a Public Cloud instance |
| Service Bus | Rebuild | Self-hosted RabbitMQ on a Public Cloud instance |
| Azure SQL | Rebuild | Self-hosted database on a Public Cloud instance |
| Log Analytics, Application Insights | Rebuild | Grafana with Loki and Prometheus on an instance |
| Anything else | decided by the AI (one question per type, asked in parallel) | |

### Dependencies between resources

Some resources can only be created after another exists on Leaseweb: a VM needs its network, and an app needs the database or vault it connects to. Assess finds these links and shows them in the **Needs first** column, together with a step number (step 1 needs nothing, step 2 needs something from step 1, and so on). The table lists resources in step order, lowest first, with **Included** resources last.

- **From the configuration:** when a resource's settings contain the id of another discovered resource (a VM's network interface points to a subnet, and the subnet to its virtual network and security group), that is a dependency. These links are certain.
- **From the AI:** the selected AI provider reads the configurations once more and reports links that only show in app settings or names, such as an app using a Key Vault. These are tagged **AI** and should be reviewed. Unknown resource names, self-links and cycles are dropped, and the page says so.
- If the AI request fails, Assess still completes with the links found in the configuration, plus a note.
- Network interfaces, disks and public IPs count as part of their VM.

Manual migration tells the AI what each plan's resource needs first, and Automatic migration orders its calls by these links, on top of the IDs a call needs from an earlier call.

The rules live in `migration_assistant/assess.py`. Every Leaseweb operation the app shows or sends must exist in the OpenAPI specs under `leaseweb-api/`. An operation an AI invents is dropped, with a warning.

## Quick start

### Requirements

- Python 3.10 or newer
- The [Azure CLI](https://learn.microsoft.com/cli/azure/) (`az`), logged in with `az login`, with access to the resource group you want to read
- At least one AI provider: Claude Code, an Anthropic API key, or opencode (see [AI providers](#ai-providers))

### Install and run

The start scripts create a virtual environment on first run, install the requirements when they change, and start the server:

```bash
./start.sh            # Linux and macOS
start.bat             # Windows (or .\start.ps1 in PowerShell)
```

Options: `--port 9000` (`-Port 9000` on Windows), `--host`, and `--reload` for development.

Or do it by hand:

```bash
pip install -r requirements.txt
python3 -m uvicorn migration_assistant.app:app
```

Open <http://127.0.0.1:8000>. The server binds to localhost only. It is a single-user tool and has no login, so do not expose it to a network.

Because it can send live Leaseweb calls, the app refuses changing requests that come from another site's page (it checks `Origin`), and it only answers to `localhost` or an IP address in the `Host` header, which blocks DNS-rebinding pages. To open it by another name, list that name in `ALLOWED_HOSTS`, for example `ALLOWED_HOSTS=devbox.lan`.

### Mock mode: try the app without Azure, AI tokens or a Leaseweb key

Each outside service can be mocked on its own, so you can, for example, read your real Azure resource group but use a canned AI and a fake Leaseweb API:

| Switch | Start script | What it does |
|---|---|---|
| `MOCK_AZURE=1` | `--mock-azure` / `-MockAzure` | Discover returns a saved, scrubbed copy of `hackaton-2026-rg` (33 resources, `migration_assistant/mock_data/`). `az` is not used. |
| `MOCK_AI=1` | `--mock-ai` / `-MockAi` | Assess and Manual migration get canned answers, so no tokens are spent. The answers follow the real configuration: dependencies come from the endpoints and names in each resource's settings. |
| `MOCK_LEASEWEB=1` | `--mock-leaseweb` / `-MockLeaseweb` | The app starts with a mock key, and live calls and teardown go to a fake Leaseweb API. Nothing is sent to Leaseweb. Remove the key to go back to dry run. |
| `MOCK_MODE=1` | `--mock` / `-Mock` | All three. Nothing leaves your machine. |

```bash
./start.sh --mock-ai --mock-leaseweb        # Linux and macOS: real Azure, mocked AI and Leaseweb
.\start.ps1 -MockAi -MockLeaseweb            # Windows PowerShell (start.bat takes the same switches)
```

To make a choice the default, put the switches in a `.env` file (see [The .env file](#the-env-file)). A banner in the app says which parts are mocked and which are real. Results are saved to `data/mock-state.json` whenever anything is mocked, so they never mix with real ones. Add `demo_app/api` and `demo_app/worker` as source folders to see code changes; the mock diffs pass `git apply --check`. `MOCK_DELAY=0` removes the short pauses that make the loading states visible.

### First run

The header shows three connections, each with a status dot: **Azure**, **AI** and **Leaseweb**. Click one to see and change its settings. **Discover** also lists them under *Before you start*, says what each one is needed for, and links to the fix when one is not ready. The app will not run a step whose prerequisite is missing:

| Connection | Needed for | Checked how |
|---|---|---|
| Azure | Discover (required) | `az account show`: is the CLI installed and signed in, as whom. Pick the subscription Discover reads; your `az` default is not changed. |
| AI provider | Assess of unknown types and Manual migration (required for plans) | The provider must be installed or have a key. **Test connection** sends one tiny request. |
| Leaseweb | Live runs only (optional) | On save, the key is checked with one read-only call. A key Leaseweb rejects is removed again, so a wrong key never leaves the app in live mode. |

1. On **Discover**, enter a resource group and click **Discover resources**. For a large group this takes a while, because each resource's configuration is fetched.
2. Continue to **Assess** and review the routes.
3. On **Manual migration**, optionally add source folders, then **Generate plan**.
4. On **Automatic migration**, review and fill in the values, then **Run dry-run migration**.

`sample_app/` is a small Python app that uses Key Vault and Blob Storage. Use it as a source folder to see code changes in a plan.

## Configuration

### The .env file

Settings can be kept in a `.env` file in the repo root instead of being set before every start. Copy `.env.example` to `.env` and uncomment what you need: `MOCK_MODE`, `MOCK_AZURE`, `MOCK_AI`, `MOCK_LEASEWEB`, `MOCK_DELAY`, `AI_PROVIDER`, `AI_MODEL`, `ANTHROPIC_API_KEY` and `ALLOWED_HOSTS`. The app reads it when it starts. A variable already set in the environment wins over the file, so `MOCK_AI=0` on the command line still turns that mock off. `.env` is git-ignored. Host and port are options of the start scripts and are not read from it.

### AI providers

Choose what writes the plans with the **AI** button in the header. Pick a provider and a model from the dropdowns, **Save**, then **Test connection** to check the setup before a long run.

| Provider | Needs | Notes |
|---|---|---|
| **Claude Code (CLI)**, the default | `claude` on PATH, logged in | Model: Default, Opus, Sonnet or Haiku. The prompt goes on stdin, so large source folders work. |
| **Anthropic API** | An API key | Paste it in the panel, or set `ANTHROPIC_API_KEY`. The model list is loaded live from Anthropic once a key exists. The default model is `claude-opus-5-5`. |
| **opencode** | `opencode` on PATH with a provider configured | The model list is read from `opencode models`. It runs in an empty scratch folder, so it cannot touch your project. |

To start with a different provider, set `AI_PROVIDER` (`claude-cli`, `anthropic-api` or `opencode`) and optionally `AI_MODEL` before starting the server. The selection made in the page is kept in memory and resets when the server restarts.

### Leaseweb API key and live mode

Without a Leaseweb key the app only does dry runs: it shows what it would send and sends nothing. Click **Leaseweb key**, paste the key and save. The header then shows **LIVE**, a red band appears under it, and Automatic migration sends real calls.

- The key is kept in server memory only. It is never written to disk, returned by any endpoint or included in an export. It is lost when the server stops.
- A live run lists exactly which calls will be sent and which will be skipped, and waits for an explicit **Send**. A single live call asks the same way.
- A call that still has a placeholder value is skipped, never guessed. A call is also skipped when the ID it needs comes from an earlier call that has not succeeded.
- Live calls can create billable resources. Try one cheap call, such as a security group, first.

### Saved state and reset

Results are saved to `data/state.json` (git-ignored), so a page refresh or server restart loses nothing. The API keys are not saved. **Start over** in the header deletes the saved results after an inline confirmation. Re-running a stage warns you first when it would clear later stages.

## Using Automatic migration

Each call shows the Leaseweb operation, the Azure resource it is for, and one labelled input per value. Names, the region and the OS disk size are prefilled from the discovered resource. Fixed lists from the Leaseweb specs, such as regions, instance types and contract type, are dropdowns. With a key set, the region list is loaded live from Leaseweb.

- Calls run in dependency order (the Needs first links from Assess, then the IDs calls need from each other). The ID a call returns (an instance, a security group, a private network) is filled into the later calls that need it, and the Status column says where each ID comes from.
- **Run** on a row runs just that call, and the remembered IDs carry over between runs. **Run dry-run migration** (or **Run LIVE migration**) runs every call that has not been sent yet.
- A value you must supply yourself is marked with `*`. For example, bucket creation needs the ID of an existing Object Storage product from your Leaseweb account.
- **Rebuild resources get their instance too.** For each Rebuild resource with a plan, the instance (and bucket) its plan needs is added, with a `userData` cloud-init that installs the replacement. The script is a starting point: review it before a live run.
- **Waiting for instances.** In a live run, a launched instance is polled until it is `RUNNING` (up to 10 minutes) before the calls that attach it to a network or security group. If it fails or does not come up, those calls are skipped.
- **Removing what was created.** In live mode, **Remove what this migration created** deletes the instances, buckets, security groups and private networks made by live calls, newest first, after a confirmation. The list is kept in server memory, so it is lost when the server stops.
- **Cost estimate.** A monthly compute estimate for the instances, priced live from your account when a key is set (otherwise from the spec examples, which cover only some types), next to the Azure VMs' Linux pay-as-you-go price from the public Azure Retail Prices API (only the VM size and region are sent). Storage, traffic and licences are not included.
- **Data migration.** The commands that copy the data: `rclone` for blobs, a Cosmos DB export into `mongoimport`, a Key Vault to Vault pipe, and notes for queues and SQL. They are for you to run; the app never runs them.
- **Exports.** **Download as curl script** gives a bash script that sends the calls with `curl` and `jq`, chaining IDs through shell variables and reading the key from `LSW_API_KEY`. **Download as JSON** gives the calls as data. **Export plan** (Markdown) now includes the data migration steps.

## Architecture

```
Browser ── FastAPI app ──┬── az CLI ........ Azure (read-only)
(static HTML/JS)         ├── AI provider ... claude -p | Anthropic API | opencode run
                         ├── leaseweb-api/ . OpenAPI specs (the source of truth for operations)
                         └── Leaseweb API .. only when a key is set (X-LSW-Auth)
```

| Module | Role |
|---|---|
| `azure_discovery.py` | Lists a resource group and fetches each resource's configuration, plus the containers, queues, tables and shares of storage accounts. Sensitive values (passwords, keys, connection strings, and name/value settings whose name looks secret) are redacted. |
| `assess.py` | The routing rules, and AI classification of unknown types. |
| `dependencies.py` | Finds which resources must exist before another: links in configurations plus AI-suggested links, checked for unknown names and cycles. |
| `plan.py` | Builds plans in parallel; reads source folders (code and manifests, skipping `.venv`, `node_modules` and the like); for large sources, first asks which files matter to each resource; validates operations against the specs. |
| `diffcheck.py` | Checks each code change with `git apply --check` and builds the `.patch` download. |
| `cloudinit.py` | The starting-point cloud-init for each kind of rebuilt service. |
| `costs.py` | Leaseweb instance prices and Azure VM prices for the cost estimate. |
| `datamove.py` | The data migration commands. |
| `dryrun.py` | Builds the prefilled calls and orders them by dependency; runs them through the dry-run or the live executor; chains returned IDs; waits for instances; records and removes what live calls created; writes the curl script. |
| `leaseweb_ops.py` | Reads operation IDs, methods, paths and allowed values from the OpenAPI specs. |
| `llm.py`, `claude_cli.py` | The AI providers behind one `ask(prompt) -> dict` function, which retries once when an answer is not valid JSON. |
| `app.py` | The FastAPI routes, the saved state and the in-memory keys. |
| `templates/`, `static/` | The UI. Plain HTML, CSS and JavaScript, with no build step. |

The app is built around injectable pieces (the `az` runner, the AI function, the HTTP client), so the tests run without Azure, an AI or Leaseweb.

## Development

```bash
python3 -m pytest
```

The tests cover the backend modules and the routes with fakes. A few static checks guard the JavaScript against duplicate function names. The UI itself has no browser test suite.

The design and the implementation plan are in `docs/superpowers/`.

## The source workload: `demo_app/`

`demo_app/` is the Azure workload this tool is meant to migrate: a small Products API on Azure Container Apps, a Functions worker, Cosmos DB, a Storage Queue and Key Vault, deployed with Terraform. See [`demo_app/README.md`](demo_app/README.md) for its architecture and deployment. Its resources carry a `workload=products-demo` tag.

## Limitations

- **Live mode is lightly tested.** The live calls have been exercised against a fake Leaseweb endpoint. Read-only calls (listing resources and regions) have been used against the real API. Treat the first real run with care.
- **Object Storage needs an existing product.** Creating a bucket needs the ID of an Object Storage product that already exists in your Leaseweb account.
- **Virtual networks map to the bare-metal private network API.** That is the create operation the specs offer. Attaching an instance to a private network takes no body in the spec, so it is up to the account which network it joins.
- **Regions are approximate.** The Azure to Leaseweb region table is a nearest-location guess covering common regions. Unknown locations keep the Amsterdam default.
- **Dependencies are best effort.** Configuration links are certain, but AI-suggested ones can be wrong or incomplete. A missing link means a call may run too early.
- **Resource types.** Only the types in the table above have rules. Others are classified by the AI and should be reviewed.
- **Source size.** Code analysis reads code and manifest files (Python, JavaScript and TypeScript, Terraform, shell, YAML, `requirements.txt`, `package.json`), up to about 200 KB in total across the chosen folders. Files over 60 KB and files that often hold secrets (`.env`, `*.tfvars`, `local.settings.json`) are skipped.
- **Container Apps and container registries** have no rule and are classified by the AI.
- **Cost and data steps are estimates and templates.** Prices exclude storage and traffic; the data commands need values filled in and should be tried on a copy first.
- **Single user, local.** There is no authentication, and state is shared by all browser tabs.
- **AI output needs review.** Plans and code diffs are AI-generated suggestions, not verified migrations.

## License

Apache License 2.0, see [LICENSE](LICENSE) and [NOTICE](NOTICE). You may use, modify and redistribute this project, commercially or not. Third-party material keeps its own terms: the Azure icons are used under Microsoft's terms and the Leaseweb logo is a trademark. [NOTICE](NOTICE) lists them and says how to remove them.

## Third-party assets

- `leaseweb-api/` is a vendored copy of Leaseweb's OpenAPI definitions. See its own README and license.
- The Azure service icons in `migration_assistant/static/azure-icons/` come from Microsoft's Azure Public Service Icons set and are used under Microsoft's terms, which are included as `Microsoft_Terms_of_Use.pdf`.
- The Leaseweb logo is Leaseweb's trademark.
