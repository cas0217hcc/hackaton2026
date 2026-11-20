# ---------- application storage: product images (Blob) + products command queue (Queue) ----------
resource "azurerm_storage_account" "app" {
  name                            = substr("st${local.compact}app", 0, 24)
  location                        = local.location
  resource_group_name             = local.rg_name
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags                            = merge(local.tags, { component = "app-storage" })

  # Private only: no public endpoint; the apps use private endpoints in vnet-hack (network.tf).
  # default_action = Deny is also what the subscription policy requires.
  public_network_access_enabled = false
  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]
  }

  blob_properties {
    versioning_enabled = true
    delete_retention_policy {
      days = 7
    }
  }
}

resource "azurerm_storage_container" "images" {
  name                  = "product-images"
  storage_account_id    = azurerm_storage_account.app.id
  container_access_type = "private"
}

resource "azurerm_storage_queue" "products" {
  name               = "products"
  storage_account_id = azurerm_storage_account.app.id
}

# The Functions runtime moves messages here after maxDequeueCount failures (our "DLQ").
# Created up front so it's visible in the portal before the first failure.
resource "azurerm_storage_queue" "products_poison" {
  name               = "products-poison"
  storage_account_id = azurerm_storage_account.app.id
}

# API: upload product images, enqueue product commands
resource "azurerm_role_assignment" "api_images" {
  scope                = azurerm_storage_account.app.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
}

resource "azurerm_role_assignment" "api_queue_send" {
  scope                = azurerm_storage_account.app.id
  role_definition_name = "Storage Queue Data Message Sender"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
}

# Worker: read/delete queue messages, re-enqueue delayed retries, write to the poison queue
resource "azurerm_role_assignment" "worker_queue" {
  scope                = azurerm_storage_account.app.id
  role_definition_name = "Storage Queue Data Contributor"
  principal_id         = azurerm_user_assigned_identity.worker.principal_id
}

# Worker: remove the image when a product is deleted
resource "azurerm_role_assignment" "worker_images" {
  scope                = azurerm_storage_account.app.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.worker.principal_id
}

# ---------- Functions host storage (runtime + deployment package) ----------
resource "azurerm_storage_account" "func" {
  name                            = substr("st${local.compact}func", 0, 24)
  location                        = local.location
  resource_group_name             = local.rg_name
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags                            = merge(local.tags, { component = "function-runtime" })

  # Private only: no public endpoint; the apps use private endpoints in vnet-hack (network.tf).
  # default_action = Deny is also what the subscription policy requires.
  public_network_access_enabled = false
  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]
  }
}

resource "azurerm_storage_container" "func_deploy" {
  name                  = "deployments"
  storage_account_id    = azurerm_storage_account.func.id
  container_access_type = "private"
}

resource "azurerm_role_assignment" "worker_func_blob" {
  scope                = azurerm_storage_account.func.id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = azurerm_user_assigned_identity.worker.principal_id
}

resource "azurerm_role_assignment" "worker_func_queue" {
  scope                = azurerm_storage_account.func.id
  role_definition_name = "Storage Queue Data Contributor"
  principal_id         = azurerm_user_assigned_identity.worker.principal_id
}

resource "azurerm_role_assignment" "worker_func_table" {
  scope                = azurerm_storage_account.func.id
  role_definition_name = "Storage Table Data Contributor"
  principal_id         = azurerm_user_assigned_identity.worker.principal_id
}
