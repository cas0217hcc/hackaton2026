resource "azurerm_cosmosdb_account" "cosmos" {
  name                         = "cosmos-${local.name}"
  location                     = local.location
  resource_group_name          = local.rg_name
  offer_type                   = "Standard"
  kind                         = "GlobalDocumentDB" # NoSQL API
  local_authentication_enabled = false              # Entra ID / managed identity only
  tags                         = merge(local.tags, { component = "database" })

  capabilities {
    name = "EnableServerless" # pay-per-request, ideal for a demo
  }

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = local.location
    failover_priority = 0
  }
}

resource "azurerm_cosmosdb_sql_database" "shop" {
  name                = "shop"
  resource_group_name = local.rg_name
  account_name        = azurerm_cosmosdb_account.cosmos.name
}

resource "azurerm_cosmosdb_sql_container" "products" {
  name                  = "products"
  resource_group_name   = local.rg_name
  account_name          = azurerm_cosmosdb_account.cosmos.name
  database_name         = azurerm_cosmosdb_sql_database.shop.name
  partition_key_paths   = ["/category"]
  partition_key_version = 2
  default_ttl           = var.product_default_ttl_seconds
}

# Lease container for the change feed trigger (the managed identity can't create containers).
resource "azurerm_cosmosdb_sql_container" "leases" {
  name                = "leases"
  resource_group_name = local.rg_name
  account_name        = azurerm_cosmosdb_account.cosmos.name
  database_name       = azurerm_cosmosdb_sql_database.shop.name
  partition_key_paths = ["/id"]
}

# Built-in data-plane roles: ...0001 = Data Reader, ...0002 = Data Contributor
resource "azurerm_cosmosdb_sql_role_assignment" "api_reader" {
  resource_group_name = local.rg_name
  account_name        = azurerm_cosmosdb_account.cosmos.name
  role_definition_id  = "${azurerm_cosmosdb_account.cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000001"
  principal_id        = azurerm_user_assigned_identity.api.principal_id
  scope               = azurerm_cosmosdb_account.cosmos.id
}

resource "azurerm_cosmosdb_sql_role_assignment" "worker_contributor" {
  resource_group_name = local.rg_name
  account_name        = azurerm_cosmosdb_account.cosmos.name
  role_definition_id  = "${azurerm_cosmosdb_account.cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azurerm_user_assigned_identity.worker.principal_id
  scope               = azurerm_cosmosdb_account.cosmos.id
}
