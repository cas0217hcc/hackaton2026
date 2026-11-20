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
| **3. Manual migration** | For each Rebuild resource, an AI writes a Leaseweb infrastructure proposal with migration steps and the Leaseweb operations involved. If you give it source folders (up to 5), it also proposes code changes as diffs, for example replacing the Key Vault SDK with a Vault client. Plans are generated in parallel with a progress bar. |
| **4. Automatic migration** | Lists the Leaseweb API calls that migrate the Direct resources, ordered by the dependencies found at Assess, with the values prefilled from what Discover found. It runs as a **dry run** by default. With a Leaseweb API key set, it sends the calls for real. |

### How resources are classified

| Azure resource | Route | Leaseweb target |
|---|---|---|
| Virtual machine | Direct | Public Cloud instance (`launchInstance`) |
| Network security group | Direct | Security group and firewall rules |
| Storage account | Direct | Object Storage bucket |
| Virtual network | Direct | Private network |
| Network interface, managed disk, public IP | Included | Part of their VM (or private endpoint); nothing to migrate separately |
| Key Vault | Rebuild | HashiCorp Vault on a Public Cloud instance |
| App Service / Functions | Rebuild | App on a Public Cloud instance |
| Cosmos DB | Rebuild | Self-hosted MongoDB on a Public Cloud instance |
| Service Bus | Rebuild | Self-hosted RabbitMQ on a Public Cloud instance |
| Azure SQL | Rebuild | Self-hosted database on a Public Cloud instance |
| Anything else | decided by the AI | |

### Dependencies between resources

Some resources can only be created after another exists on Leaseweb: a VM needs its network, and an app needs the database or vault it connects to. Assess finds these links and shows them in the **Needs first** column, together with a step number (step 1 needs nothing, step 2 needs something from step 1, and so on).

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

### First run

1. On **Discover**, enter a resource group and click **Discover resources**. For a large group this takes a while, because each resource's configuration is fetched.
2. Continue to **Assess** and review the routes.
3. On **Manual migration**, optionally add source folders, then **Generate plan**.
4. On **Automatic migration**, review and fill in the values, then **Run dry-run migration**.

`sample_app/` is a small Python app that uses Key Vault and Blob Storage. Use it as a source folder to see code changes in a plan.

## Configuration

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

## Architecture

```
Browser ── FastAPI app ──┬── az CLI ........ Azure (read-only)
(static HTML/JS)         ├── AI provider ... claude -p | Anthropic API | opencode run
                         ├── leaseweb-api/ . OpenAPI specs (the source of truth for operations)
                         └── Leaseweb API .. only when a key is set (X-LSW-Auth)
```

| Module | Role |
|---|---|
| `azure_discovery.py` | Lists a resource group and fetches each resource's configuration. Sensitive values (passwords, keys, connection strings) are redacted. |
| `assess.py` | The routing rules, and AI classification of unknown types. |
| `dependencies.py` | Finds which resources must exist before another: links in configurations plus AI-suggested links, checked for unknown names and cycles. |
| `plan.py` | Builds plans in parallel; reads Python source folders; validates operations against the specs. |
| `dryrun.py` | Builds the prefilled calls and orders them by dependency; runs them through the dry-run or the live executor; chains returned IDs. |
| `leaseweb_ops.py` | Reads operation IDs, methods, paths and allowed values from the OpenAPI specs. |
| `llm.py`, `claude_cli.py` | The AI providers behind one `ask(prompt) -> dict` function. |
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
- **Python source only.** Code analysis reads `.py` files, up to about 200 KB in total across the chosen folders.
- **Single user, local.** There is no authentication, and state is shared by all browser tabs.
- **AI output needs review.** Plans and code diffs are AI-generated suggestions, not verified migrations.

## License

Apache License 2.0, see [LICENSE](LICENSE) and [NOTICE](NOTICE). You may use, modify and redistribute this project, commercially or not. Third-party material keeps its own terms: the Azure icons are used under Microsoft's terms and the Leaseweb logo is a trademark. [NOTICE](NOTICE) lists them and says how to remove them.

## Third-party assets

- `leaseweb-api/` is a vendored copy of Leaseweb's OpenAPI definitions. See its own README and license.
- The Azure service icons in `migration_assistant/static/azure-icons/` come from Microsoft's Azure Public Service Icons set and are used under Microsoft's terms, which are included as `Microsoft_Terms_of_Use.pdf`.
- The Leaseweb logo is Leaseweb's trademark.
