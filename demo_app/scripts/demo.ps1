<#
.SYNOPSIS
  Demo walkthrough of the Products API:
    1. create + read + update + image  (happy path)
    2. transient failure -> scheduled retries via queue visibility timeout -> applied
    3. poison command    -> 3 attempts -> 'products-poison' queue
    4. delete            -> soft delete, change feed notification, TTL purge
#>
param([string]$ApiUrl = "", [string]$ApiKey = "")

$ErrorActionPreference = "Stop"
$infra = Join-Path (Split-Path -Parent $PSScriptRoot) "infra"
if (-not $ApiUrl) { $ApiUrl = terraform -chdir="$infra" output -raw api_url }
if (-not $ApiKey) {
  $kv = (terraform -chdir="$infra" output -raw key_vault_name)
  $ApiKey = az keyvault secret show --vault-name $kv -n products-api-key --query value -o tsv
}
$h = @{ "X-API-Key" = $ApiKey }

function Send-Product([string]$method, [string]$path, [hashtable]$body) {
  Invoke-RestMethod -Method $method -Uri "$ApiUrl$path" -Headers $h -ContentType "application/json" -Body ($body | ConvertTo-Json)
}

Write-Host "== 1. Happy path ==" -ForegroundColor Cyan
$p = Send-Product POST "/products" @{ name = "VPS Small"; category = "compute"; price = 9.99; stock = 100 }
$p | Format-List
Start-Sleep -Seconds 8
Invoke-RestMethod "$ApiUrl/products/$($p.id)" | Format-List
Send-Product PUT "/products/$($p.id)" @{ name = "VPS Small"; category = "compute"; price = 7.99; stock = 80 } | Out-Null
Start-Sleep -Seconds 8
Invoke-RestMethod "$ApiUrl/products?category=compute" | Format-Table id, name, price, stock

Write-Host "== 2. Transient failure -> retries after 10s, 20s -> applied ==" -ForegroundColor Cyan
$t = Send-Product POST "/products?simulate=transient" @{ name = "Object Storage 1TB"; category = "storage"; price = 4.50 }
Write-Host "id $($t.id): 404 for ~30s, then it appears:  Invoke-RestMethod $ApiUrl/products/$($t.id)"

Write-Host "== 3. Poison -> 3 attempts -> 'products-poison' queue ==" -ForegroundColor Cyan
$x = Send-Product POST "/products?simulate=poison" @{ name = "Broken product"; category = "misc"; price = 1 }
Write-Host "id $($x.id) never appears; see it in the products-poison queue (portal -> storage account -> Queues)."

Write-Host "== 4. Promo product with its own TTL (expires after 120s) ==" -ForegroundColor Cyan
Send-Product POST "/products" @{ name = "Black Friday Bundle"; category = "promo"; price = 0.99; ttlSeconds = 120 } | Format-List

Write-Host "== 5. Delete (soft delete -> change feed 'ProductDeleted' -> TTL purge) ==" -ForegroundColor Cyan
Invoke-RestMethod -Method Delete -Uri "$ApiUrl/products/$($p.id)" -Headers $h | Format-List
Write-Host "Notifier output: App Insights -> traces | where message startswith 'NOTIFY'"
