data "azurerm_client_config" "current" {}

resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

locals {
  suffix = random_string.suffix.result
  name   = "${var.prefix}-${local.suffix}"
  # alphanumeric-only names (storage, ACR)
  compact = "${var.prefix}${local.suffix}"

  # The "component" tag lets the migration tooling discover and map each resource.
  tags = merge({
    workload    = "products-demo"
    environment = "hackathon"
    managed-by  = "terraform"
  }, var.tags)
}

# ---------- resource group: existing (default) or created by Terraform ----------
data "azurerm_resource_group" "existing" {
  count = var.create_resource_group ? 0 : 1
  name  = var.resource_group_name
}

resource "azurerm_resource_group" "rg" {
  count    = var.create_resource_group ? 1 : 0
  name     = var.resource_group_name
  location = var.location
  tags     = local.tags
}

locals {
  rg_name = var.create_resource_group ? azurerm_resource_group.rg[0].name : data.azurerm_resource_group.existing[0].name
  # resources default to the resource group's region unless `location` is set
  location = coalesce(
    var.location,
    var.create_resource_group ? null : data.azurerm_resource_group.existing[0].location
  )
}

# ---------- observability ----------
resource "azurerm_log_analytics_workspace" "logs" {
  name                = "log-${local.name}"
  location            = local.location
  resource_group_name = local.rg_name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = merge(local.tags, { component = "monitoring" })
}

resource "azurerm_application_insights" "ai" {
  name                = "appi-${local.name}"
  location            = local.location
  resource_group_name = local.rg_name
  workspace_id        = azurerm_log_analytics_workspace.logs.id
  application_type    = "web"
  tags                = merge(local.tags, { component = "monitoring" })
}

# ---------- identities (one per app, least privilege) ----------
resource "azurerm_user_assigned_identity" "api" {
  name                = "id-${local.name}-api"
  location            = local.location
  resource_group_name = local.rg_name
  tags                = merge(local.tags, { component = "identity" })
}

resource "azurerm_user_assigned_identity" "worker" {
  name                = "id-${local.name}-worker"
  location            = local.location
  resource_group_name = local.rg_name
  tags                = merge(local.tags, { component = "identity" })
}
