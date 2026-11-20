# Leaseweb API documentation

Source: https://github.com/leaseweb/api-definitions (official OpenAPI definitions), commit `1d97cc8f9fe8945b2455d665694880e97e56a944`, fetched 2026-11-17. Licence in `LICENSE`.
Rendered docs: https://developer.leaseweb.com/api-docs/ (for example `publiccloud_v1.html`). An OpenAPI file WAS found (this repo), so the fake derives its rules from it, not from hand-written page notes.
Auth header: `X-LSW-Auth`.

## Products in scope

Chosen from the provisioners in `hackaton2026/mapping/azure-leaseweb.yaml` (instance, private_network, security_group, object_storage):

- publicCloud: instances, security groups, load balancers
- privateNetworks: private networks
- objectStorage: object storage

Each product directory holds `openapi.yaml` plus `paths/`, `components/` referenced with `$ref`.

## claude -p status

`claude -p "reply with the word ok"` works with the current login (checked 2026-11-17). The CLI warned that the sign-in ends between 2026-11-21 and 2026-11-24: run `claude auth login` before then, or `claude setup-token` for unattended jobs. If it ever fails, use `PromptFileRunner` and run the prompt by hand.
