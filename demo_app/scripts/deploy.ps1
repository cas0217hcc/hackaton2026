<#
.SYNOPSIS
  End-to-end deploy of the Products demo: infra -> API image -> Container App -> Function code.

.DESCRIPTION
  Subscription and resource group are REQUIRED - taken from the parameters or, if omitted,
  from infra/terraform.tfvars. Nothing is inferred from your az context.
  Only parameters you pass explicitly override terraform.tfvars.
  The script shows a terraform plan and asks for confirmation before changing anything.

.EXAMPLE
  az login
  ./scripts/deploy.ps1                                   # everything from infra/terraform.tfvars
  ./scripts/deploy.ps1 -SubscriptionId <sub-guid> -ResourceGroup rg-hackathon-products
  ./scripts/deploy.ps1 -SubscriptionId <sub-guid> -ResourceGroup rg-new -CreateResourceGroup -Location westeurope
#>
param(
  [string]$SubscriptionId = "",
  [string]$ResourceGroup = "",
  [switch]$CreateResourceGroup,
  [string]$Location = "",
  [string]$Prefix = "",
  [string]$ImageTag = (Get-Date -Format "yyyyMMddHHmmss"),
  [switch]$AutoApprove
)

$ErrorActionPreference = "Stop"
$root  = Split-Path -Parent $PSScriptRoot
$infra = Join-Path $root "infra"

function Invoke-Checked([scriptblock]$cmd) {
  & $cmd
  if ($LASTEXITCODE -ne 0) { throw "Command failed: $cmd" }
}

function Get-TfVar([string]$name) {
  $file = Join-Path $infra "terraform.tfvars"
  if (-not (Test-Path $file)) { return "" }
  $m = Select-String -Path $file -Pattern "^\s*$name\s*=\s*`"?([^`"#]*?)`"?\s*(#.*)?$" | Select-Object -First 1
  if ($m) { return $m.Matches[0].Groups[1].Value.Trim() } else { return "" }
}

$tfVars = @()
if ($SubscriptionId) { $tfVars += "-var=subscription_id=$SubscriptionId" } else { $SubscriptionId = Get-TfVar "subscription_id" }
if ($ResourceGroup)  { $tfVars += "-var=resource_group_name=$ResourceGroup" } else { $ResourceGroup = Get-TfVar "resource_group_name" }
if ($CreateResourceGroup) { $tfVars += "-var=create_resource_group=true" }
if ($Location) { $tfVars += "-var=location=$Location" }
if ($Prefix)   { $tfVars += "-var=prefix=$Prefix" }

if (-not $SubscriptionId -or $SubscriptionId -like "<*") { throw "Set -SubscriptionId or subscription_id in infra/terraform.tfvars" }
if (-not $ResourceGroup -or $ResourceGroup -like "<*") { throw "Set -ResourceGroup or resource_group_name in infra/terraform.tfvars" }

Write-Host "Subscription : $SubscriptionId" -ForegroundColor Cyan
Write-Host "ResourceGroup: $ResourceGroup" -ForegroundColor Cyan

# Pin the az CLI to the same subscription Terraform uses (acr build / function deploy).
Invoke-Checked { az account set --subscription $SubscriptionId }

# 1) Infrastructure (everything except the Container App, which needs an image)
Write-Host "`n[1/4] terraform plan/apply (infrastructure)" -ForegroundColor Cyan
Invoke-Checked { terraform -chdir="$infra" init -upgrade }
# On re-runs keep the currently deployed image so the Container App isn't destroyed.
$prevImage = ""
try { $prevImage = terraform -chdir="$infra" output -raw api_image 2>$null } catch {}
if ($LASTEXITCODE -ne 0) { $prevImage = "" }
$phase1Vars = $tfVars + @("-var=api_image=$prevImage")

Invoke-Checked { terraform -chdir="$infra" plan -out=phase1.tfplan @phase1Vars }
if (-not $AutoApprove) {
  $answer = Read-Host "Apply this plan to subscription $SubscriptionId / $ResourceGroup? (yes/no)"
  if ($answer -ne "yes") { Write-Host "Aborted."; exit 1 }
}
Invoke-Checked { terraform -chdir="$infra" apply phase1.tfplan }

$rg  = terraform -chdir="$infra" output -raw resource_group
$acr = terraform -chdir="$infra" output -raw acr_name
$acrServer = terraform -chdir="$infra" output -raw acr_login_server
$func = terraform -chdir="$infra" output -raw function_app_name

# 2) Build the API image in the cloud (no local Docker needed)
Write-Host "`n[2/4] az acr build (products-api:$ImageTag)" -ForegroundColor Cyan
Invoke-Checked { az acr build --registry $acr --image "products-api:$ImageTag" (Join-Path $root "api") }
$image = "$acrServer/products-api:$ImageTag"

# 3) Container App with the new image
Write-Host "`n[3/4] terraform apply (Container App -> $image)" -ForegroundColor Cyan
Invoke-Checked { terraform -chdir="$infra" apply -auto-approve @tfVars "-var=api_image=$image" }

# 4) Function code (remote build installs requirements.txt on Linux)
Write-Host "`n[4/4] deploy Function app code" -ForegroundColor Cyan
$zip = Join-Path ([IO.Path]::GetTempPath()) "products-worker.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
$worker = Join-Path $root "worker"
Compress-Archive -Path (Join-Path $worker "function_app.py"), (Join-Path $worker "host.json"), (Join-Path $worker "requirements.txt") -DestinationPath $zip
Invoke-Checked { az functionapp deployment source config-zip -g $rg -n $func --src $zip --build-remote true }

$api = terraform -chdir="$infra" output -raw api_url
Write-Host "`nDone. API: $api  (Swagger UI: $api/docs)" -ForegroundColor Green
Write-Host "Get the write API key with:  ./scripts/demo.ps1  (or: az keyvault secret show --vault-name <kv> -n products-api-key --query value -o tsv)"
