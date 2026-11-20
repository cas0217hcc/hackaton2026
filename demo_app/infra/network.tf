# ---------- networking: reuse an existing VNet, add app subnets + private endpoints ----------
# The storage accounts are private-only (public network access disabled). The apps reach them
# through private endpoints in vnet-hack:
#   Container Apps env  -> snet-...-cae   (VNet-injected)
#   Function app        -> snet-...-func  (VNet integration)
#   storage endpoints   -> snet-...-pe    (private endpoints, resolved via private DNS zones)
# Terraform manages only the subnets/zones/endpoints below, never the VNet itself.

data "azurerm_virtual_network" "vnet" {
  name                = var.vnet_name
  resource_group_name = coalesce(var.vnet_resource_group_name, local.rg_name)
}

resource "azurerm_network_security_group" "apps" {
  name                = "nsg-${local.name}-apps"
  location            = local.location
  resource_group_name = local.rg_name
  tags                = merge(local.tags, { component = "network" })
  # default rules only: VNet-internal + Azure LB inbound, all outbound
}

# Container Apps environment (workload-profiles env -> /27 minimum, delegated)
resource "azurerm_subnet" "cae" {
  name                 = "snet-${local.name}-cae"
  resource_group_name  = data.azurerm_virtual_network.vnet.resource_group_name
  virtual_network_name = data.azurerm_virtual_network.vnet.name
  address_prefixes     = [var.subnet_cae_prefix]

  delegation {
    name = "containerapps"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

# Function app (Flex Consumption) VNet integration
resource "azurerm_subnet" "func" {
  name                 = "snet-${local.name}-func"
  resource_group_name  = data.azurerm_virtual_network.vnet.resource_group_name
  virtual_network_name = data.azurerm_virtual_network.vnet.name
  address_prefixes     = [var.subnet_func_prefix]

  delegation {
    name = "flexconsumption"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

# Private endpoints for the storage accounts
resource "azurerm_subnet" "pe" {
  name                 = "snet-${local.name}-pe"
  resource_group_name  = data.azurerm_virtual_network.vnet.resource_group_name
  virtual_network_name = data.azurerm_virtual_network.vnet.name
  address_prefixes     = [var.subnet_pe_prefix]
}

resource "azurerm_subnet_network_security_group_association" "cae" {
  subnet_id                 = azurerm_subnet.cae.id
  network_security_group_id = azurerm_network_security_group.apps.id
}

resource "azurerm_subnet_network_security_group_association" "func" {
  subnet_id                 = azurerm_subnet.func.id
  network_security_group_id = azurerm_network_security_group.apps.id
}

resource "azurerm_subnet_network_security_group_association" "pe" {
  subnet_id                 = azurerm_subnet.pe.id
  network_security_group_id = azurerm_network_security_group.apps.id
}

# ---------- private DNS: <account>.blob/queue/table.core.windows.net -> private IP ----------
locals {
  storage_services = ["blob", "queue", "table"]

  # account -> services it needs a private endpoint for
  storage_private_endpoints = {
    "app-blob"   = { account_id = azurerm_storage_account.app.id, service = "blob" }
    "app-queue"  = { account_id = azurerm_storage_account.app.id, service = "queue" }
    "func-blob"  = { account_id = azurerm_storage_account.func.id, service = "blob" }
    "func-queue" = { account_id = azurerm_storage_account.func.id, service = "queue" }
    "func-table" = { account_id = azurerm_storage_account.func.id, service = "table" }
  }
}

resource "azurerm_private_dns_zone" "storage" {
  for_each            = toset(local.storage_services)
  name                = "privatelink.${each.key}.core.windows.net"
  resource_group_name = local.rg_name
  tags                = merge(local.tags, { component = "network" })
}

resource "azurerm_private_dns_zone_virtual_network_link" "storage" {
  for_each              = azurerm_private_dns_zone.storage
  name                  = "link-${data.azurerm_virtual_network.vnet.name}"
  resource_group_name   = local.rg_name
  private_dns_zone_name = each.value.name
  virtual_network_id    = data.azurerm_virtual_network.vnet.id
  registration_enabled  = false
  tags                  = merge(local.tags, { component = "network" })
}

resource "azurerm_private_endpoint" "storage" {
  for_each            = local.storage_private_endpoints
  name                = "pe-${local.name}-${each.key}"
  location            = local.location
  resource_group_name = local.rg_name
  subnet_id           = azurerm_subnet.pe.id
  tags                = merge(local.tags, { component = "network" })

  private_service_connection {
    name                           = "psc-${local.name}-${each.key}"
    private_connection_resource_id = each.value.account_id
    subresource_names              = [each.value.service]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.storage[each.value.service].id]
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.storage]
}
