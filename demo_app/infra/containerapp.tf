resource "azurerm_container_registry" "acr" {
  name                = substr("acr${local.compact}", 0, 50)
  location            = local.location
  resource_group_name = local.rg_name
  sku                 = "Basic"
  admin_enabled       = false
  tags                = merge(local.tags, { component = "registry" })
}

resource "azurerm_role_assignment" "api_acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
}

resource "azurerm_container_app_environment" "env" {
  name                       = "cae-${local.name}"
  location                   = local.location
  resource_group_name        = local.rg_name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id
  tags                       = merge(local.tags, { component = "container-platform" })

  # VNet-injected so the API can reach the network-restricted storage account.
  # Ingress stays public (internal_load_balancer_enabled = false).
  infrastructure_subnet_id = azurerm_subnet.cae.id

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }

  depends_on = [azurerm_subnet_network_security_group_association.cae]
}

# Created only once an image has been pushed (see scripts/deploy.ps1).
resource "azurerm_container_app" "api" {
  count = var.api_image == "" ? 0 : 1

  name                         = "ca-${local.name}-api"
  resource_group_name          = local.rg_name
  container_app_environment_id = azurerm_container_app_environment.env.id
  revision_mode                = "Single"
  tags                         = merge(local.tags, { component = "api" })

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.api.id]
  }

  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.api.id
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1
    max_replicas = 3

    http_scale_rule {
      name                = "http"
      concurrent_requests = "50"
    }

    container {
      name   = "api"
      image  = var.api_image
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.api.client_id
      }
      env {
        name  = "STORAGE_QUEUE_ENDPOINT"
        value = azurerm_storage_account.app.primary_queue_endpoint
      }
      env {
        name  = "PRODUCTS_QUEUE"
        value = azurerm_storage_queue.products.name
      }
      env {
        name  = "STORAGE_BLOB_ENDPOINT"
        value = azurerm_storage_account.app.primary_blob_endpoint
      }
      env {
        name  = "IMAGES_CONTAINER"
        value = azurerm_storage_container.images.name
      }
      env {
        name  = "KEYVAULT_URI"
        value = azurerm_key_vault.kv.vault_uri
      }
      env {
        name  = "API_KEY_SECRET_NAME"
        value = azurerm_key_vault_secret.api_key.name
      }
      env {
        name  = "COSMOS_ENDPOINT"
        value = azurerm_cosmosdb_account.cosmos.endpoint
      }
      env {
        name  = "COSMOS_DATABASE"
        value = azurerm_cosmosdb_sql_database.shop.name
      }
      env {
        name  = "COSMOS_CONTAINER"
        value = azurerm_cosmosdb_sql_container.products.name
      }
      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.ai.connection_string
      }

      liveness_probe {
        transport = "HTTP"
        path      = "/healthz"
        port      = 8000
      }
      readiness_probe {
        transport = "HTTP"
        path      = "/healthz"
        port      = 8000
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.api_acr_pull,
    azurerm_role_assignment.api_kv,
    azurerm_role_assignment.api_images,
    azurerm_role_assignment.api_queue_send,
    azurerm_private_endpoint.storage, # app storage is private-only
    azurerm_cosmosdb_sql_role_assignment.api_reader,
  ]
}
