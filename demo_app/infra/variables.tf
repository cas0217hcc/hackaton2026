variable "subscription_id" {
  description = "Azure subscription to deploy into."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that will hold all resources."
  type        = string
}

variable "create_resource_group" {
  description = "false (default) = use an existing resource group; true = Terraform creates it (requires `location`)."
  type        = bool
  default     = false
}

variable "location" {
  description = "Azure region. Defaults to the resource group's region. West Europe sits next to Leaseweb's Amsterdam DCs."
  type        = string
  default     = null

  validation {
    condition     = !var.create_resource_group || var.location != null
    error_message = "location is required when create_resource_group = true."
  }
}

variable "prefix" {
  description = "Short lowercase name used in every resource name."
  type        = string
  default     = "products"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,9}$", var.prefix))
    error_message = "prefix must be 2-10 lowercase letters/digits and start with a letter."
  }
}

variable "api_image" {
  description = "Full image reference for the API (e.g. acrxxx.azurecr.io/products-api:v1). Leave empty on the first apply; the Container App is created once an image exists."
  type        = string
  default     = ""
}

variable "product_default_ttl_seconds" {
  description = "Container default TTL in Cosmos DB. -1 = TTL enabled but items never expire unless they set their own ttl (promo products, soft-deleted items)."
  type        = number
  default     = -1
}

variable "vnet_name" {
  description = "Existing virtual network to add the app subnets to."
  type        = string
  default     = "vnet-hack"
}

variable "vnet_resource_group_name" {
  description = "Resource group of the VNet (defaults to resource_group_name)."
  type        = string
  default     = null
}

variable "subnet_cae_prefix" {
  description = "Free address range in the VNet for the Container Apps environment (/27 or larger)."
  type        = string
  default     = "10.20.2.0/24"
}

variable "subnet_func_prefix" {
  description = "Free address range in the VNet for the Function app VNet integration."
  type        = string
  default     = "10.20.3.0/24"
}

variable "subnet_pe_prefix" {
  description = "Free address range in the VNet for the storage private endpoints."
  type        = string
  default     = "10.20.4.0/24"
}

variable "notify_webhook_url" {
  description = "Optional URL the notifier POSTs product change events to (e.g. a webhook.site URL for the demo)."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Extra tags applied to every resource."
  type        = map(string)
  default     = {}
}
