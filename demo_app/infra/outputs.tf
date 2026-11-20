output "resource_group" {
  value = local.rg_name
}

output "acr_name" {
  value = azurerm_container_registry.acr.name
}

output "acr_login_server" {
  value = azurerm_container_registry.acr.login_server
}

output "api_image" {
  value = var.api_image
}

output "function_app_name" {
  value = azurerm_function_app_flex_consumption.worker.name
}

output "api_url" {
  value = try("https://${azurerm_container_app.api[0].ingress[0].fqdn}", "(not deployed yet - set api_image)")
}

output "cosmos_endpoint" {
  value = azurerm_cosmosdb_account.cosmos.endpoint
}

output "app_storage_account" {
  description = "Holds the 'product-images' blob container and the 'products' / 'products-poison' queues."
  value       = azurerm_storage_account.app.name
}

output "key_vault_name" {
  value = azurerm_key_vault.kv.name
}

output "key_vault_uri" {
  value = azurerm_key_vault.kv.vault_uri
}
