# Azure to Leaseweb Migration Assistant: Design

Date: 2026-11-20
Status: draft for approval

## Intent

Teams moving workloads from Azure to Leaseweb find that many Azure services have no Leaseweb equivalent (managed services such as Key Vault, Functions, Cosmos DB, Service Bus). Deciding what to do about each gap, and what it means for the application code, is slow manual work.

This is a hackathon demo of a web application that reads an Azure resource group, assesses each resource's fit for Leaseweb, migrates what maps directly, and for what does not, proposes an infrastructure plan and the application code changes it requires. Judges will weigh innovation and applicability.

## Goals

- Read the resources of one Azure resource group and display them.
- Classify each resource: **Direct** (clean Leaseweb mapping) or **Rebuild** (no equivalent).
- For Direct resources, run the migration against Leaseweb in **dry-run mode**: show the exact Leaseweb API calls that would be made, send none.
- For Rebuild resources, propose a Leaseweb infrastructure replacement (for example HashiCorp Vault on a Public Cloud instance in place of Key Vault).
- When the user supplies application source code, identify the code changes the plan requires (for example replacing `azure-keyvault-secrets` calls with a Vault client), shown as file-level diffs.
- Ground proposals in what Leaseweb can actually do, using the OpenAPI specs in `leaseweb-api/` (publicCloud, objectStorage, privateNetworks).

## Non-goals

- Real execution against Leaseweb. No API key exists yet; the Migrate stage is dry-run only. The design must allow a real key to be added later without changing the flow.
- Migrating data (disk contents, blob contents, secrets).
- Writing to or changing anything in Azure. Azure access is read-only.
- Multiple subscriptions, multiple users, authentication, deployment or hosting. It runs locally.

## Anti-goals

- A tool that looks finished but invents Leaseweb capabilities. Proposals that name services or API operations Leaseweb does not offer would fail the "applicability" criterion even if the demo runs.
- A tool that mutates Azure.

## Constraints

- Language: Python.
- Azure access: the user's existing `az` CLI login, subscription "GDC - Sandbox", resource group `hackaton-2026-rg`. Read-only.
- AI: no Anthropic API key is available. Analysis calls the Claude Code CLI in headless mode (`claude -p`) as a subprocess. The demo machine needs `claude` installed and logged in.
- Source code input: the user enters a local folder path in the browser UI; the app reads the code from that folder. (Interpretation of "folder in the browser"; browser file upload is not planned.)
- Demo data in `hackaton-2026-rg`: vm-web-01 with NIC, public IP, OS disk, NSG, vnet-hack, two storage accounts (sthackb4e3bc40, st4oekee), and Key Vault kv-hack-b4e3bc40. The VM, networking and storage are expected to be Direct; Key Vault is the Rebuild case.
- A teammate team is producing the sample application whose code will be analysed. It is not yet available.

## Decided

- UI follows a **guided flow** with four stages, one decision per screen: Discover, Assess, Plan, Migrate. Operator-tool look: restrained palette, system sans-serif, monospace only for resource IDs, a table of resources with a status pill (Direct / Rebuild) and target, Export plan and Continue actions. Mockup: `.superpowers/brainstorm/88477-1795168248/content/layout-v2.html` (option A).
- Stage behaviour:
  - Discover: list resources of the resource group.
  - Assess: label each Direct or Rebuild with its Leaseweb target.
  - Plan: for Rebuild resources, an infrastructure proposal; if source code was supplied, the code changes. Plan can be exported.
  - Migrate: dry-run of the Leaseweb API calls for Direct resources.

## Confirmed by the user (review round)

- The demo calls `claude -p` live on stage. No cached or canned-response fallback. The app should still show a clear error and allow retry if a call fails or times out.

## Calls made by the author (not yet confirmed by the user)

- Where the OpenAPI specs in `leaseweb-api/` and the expectation that "VM, networking and storage are Direct" disagree, the specs win. A resource is Direct only if a spec operation covers it; otherwise it is Rebuild or unmapped. This follows the anti-goal against inventing capabilities.
- Grounding is enforced: every Leaseweb API call in a proposal or dry-run must name an operation that exists in the specs, and the app flags any that do not.
- Azure is read through `az` CLI subprocess calls with JSON output, using the existing login.
- The sample app from teammates is not available yet. Build against a small stand-in Python app (Key Vault plus storage SDK calls) and swap the real one in later. Python is the only supported source language for the demo.
- The Plan-stage infrastructure proposal is readable prose plus a structured list of the Leaseweb operations involved (also dry-run).
- Rebuild rules table covers Key Vault plus common managed services (Functions, Cosmos DB, Service Bus, Azure SQL). Unknown types are classified by Claude.
- Dry-run requests use placeholder or spec-default values for image, region and instance type. The executor sits behind an interface whose default is dry-run, so a real API key can be added later.

## Left to the builder (builder's call, mark in the plan)

- Web framework and frontend approach.
- How Direct vs Rebuild is decided: a rules table for known Azure types, with Claude used for unknown types, is a suggested starting point.
- Structure of prompts to `claude -p`, and how its output is parsed (structured JSON recommended).
- How resources map to Leaseweb API operations in the dry-run.
- Export format for the plan (Markdown suggested).
- Timeouts, progress indication and retry behaviour for live `claude -p` calls.
