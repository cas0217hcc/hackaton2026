resource "azurerm_service_plan" "func" {
  name                = "asp-${local.name}-func"
  location            = local.location
  resource_group_name = local.rg_name
  os_type             = "Linux"
  sku_name            = "FC1" # Flex Consumption
  tags                = merge(local.tags, { component = "worker" })
}

# Workaround (azurerm 4.81): the flex resource always writes an AzureWebJobsStorage connection
# string with an EMPTY account key. The Functions host prefers it over the managed-identity
# settings (AzureWebJobsStorage__accountName/__credential/__clientId), fails with 403 against
# its storage and never starts its triggers. Remove it after every create/update of the app.
resource "terraform_data" "worker_remove_webjobs_connection_string" {
  triggers_replace = [
    azurerm_function_app_flex_consumption.worker.id,
    sha256(jsonencode(azurerm_function_app_flex_consumption.worker.app_settings)),
    sha256(jsonencode(azurerm_function_app_flex_consumption.worker.always_ready)),
  ]

  provisioner "local-exec" {
    command = "az functionapp config appsettings delete --subscription ${var.subscription_id} -g ${local.rg_name} -n ${azurerm_function_app_flex_consumption.worker.name} --setting-names AzureWebJobsStorage -o none"
  }
}

resource "azurerm_function_app_flex_consumption" "worker" {
  name                = "func-${local.name}-worker"
  location            = local.location
  resource_group_name = local.rg_name
  service_plan_id     = azurerm_service_plan.func.id
  tags                = merge(local.tags, { component = "worker" })

  storage_container_type            = "blobContainer"
  storage_container_endpoint        = "${azurerm_storage_account.func.primary_blob_endpoint}${azurerm_storage_container.func_deploy.name}"
  storage_authentication_type       = "UserAssignedIdentity"
  storage_user_assigned_identity_id = azurerm_user_assigned_identity.worker.id

  # VNet integration: outbound traffic to the network-restricted storage goes via the subnet
  virtual_network_subnet_id = azurerm_subnet.func.id

  runtime_name           = "python"
  runtime_version        = "3.11"
  maximum_instance_count = 40
  instance_memory_in_mb  = 2048

  # Keep one instance warm: it polls the private queue itself (no cold start, no reliance on
  # the platform scale controller seeing the network-restricted queue). Small fixed cost.
  always_ready {
    name           = "function:apply_command"
    instance_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.worker.id]
  }

  site_config {
    application_insights_connection_string = azurerm_application_insights.ai.connection_string
    # Route ALL outbound traffic (incl. DNS) through the VNet, so *.core.windows.net resolves
    # via the private DNS zones to the storage private endpoints.
    vnet_route_all_enabled = true
  }

  app_settings = {
    AZURE_CLIENT_ID = azurerm_user_assigned_identity.worker.client_id

    # Host storage via managed identity
    AzureWebJobsStorage__accountName = azurerm_storage_account.func.name
    AzureWebJobsStorage__credential  = "managedidentity"
    AzureWebJobsStorage__clientId    = azurerm_user_assigned_identity.worker.client_id

    # Storage Queue trigger via managed identity (app storage account, not the host one)
    ProductsQueue__queueServiceUri = trimsuffix(azurerm_storage_account.app.primary_queue_endpoint, "/")
    ProductsQueue__credential      = "managedidentity"
    ProductsQueue__clientId        = azurerm_user_assigned_identity.worker.client_id
    PRODUCTS_QUEUE                 = azurerm_storage_queue.products.name
    STORAGE_BLOB_ENDPOINT          = azurerm_storage_account.app.primary_blob_endpoint
    IMAGES_CONTAINER               = azurerm_storage_container.images.name

    # Cosmos DB change feed trigger via managed identity
    CosmosDBConnection__accountEndpoint = azurerm_cosmosdb_account.cosmos.endpoint
    CosmosDBConnection__credential      = "managedidentity"
    CosmosDBConnection__clientId        = azurerm_user_assigned_identity.worker.client_id
    COSMOS_ENDPOINT                     = azurerm_cosmosdb_account.cosmos.endpoint
    COSMOS_DATABASE                     = azurerm_cosmosdb_sql_database.shop.name
    COSMOS_CONTAINER                    = azurerm_cosmosdb_sql_container.products.name

    MAX_SCHEDULED_RETRIES = "3"
    RETRY_BASE_SECONDS    = "10"
    NOTIFY_WEBHOOK_URL    = var.notify_webhook_url
  }

  depends_on = [
    azurerm_role_assignment.worker_func_blob,
    azurerm_role_assignment.worker_func_queue,
    azurerm_role_assignment.worker_func_table,
    azurerm_role_assignment.worker_queue,
    azurerm_role_assignment.worker_images,
    azurerm_private_endpoint.storage, # host storage is private-only
    azurerm_cosmosdb_sql_role_assignment.worker_contributor,
  ]
}
