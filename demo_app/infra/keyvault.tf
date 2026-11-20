resource "azurerm_key_vault" "kv" {
  name                       = "kv-${local.name}"
  location                   = local.location
  resource_group_name        = local.rg_name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  purge_protection_enabled   = false # demo: allow clean destroy
  soft_delete_retention_days = 7
  tags                       = merge(local.tags, { component = "secrets" })
}

# Whoever runs Terraform needs to write the secret.
resource "azurerm_role_assignment" "deployer_kv" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "api_kv" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
}

# RBAC assignments take a little while to propagate.
resource "time_sleep" "kv_rbac" {
  depends_on      = [azurerm_role_assignment.deployer_kv]
  create_duration = "60s"
}

resource "random_password" "api_key" {
  length  = 48
  special = false
}

resource "azurerm_key_vault_secret" "api_key" {
  name         = "products-api-key"
  value        = random_password.api_key.result
  key_vault_id = azurerm_key_vault.kv.id
  content_type = "API key required for write calls to the Products API (X-API-Key)"
  depends_on   = [time_sleep.kv_rbac]
}
