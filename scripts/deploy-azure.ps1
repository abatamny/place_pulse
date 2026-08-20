[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9._()-]{1,90}$')]
    [string]$ResourceGroup,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9-]{1,64}$')]
    [string]$VmName,

    [Parameter(Mandatory = $true)]
    [string]$SshPublicKeyPath,

    [Parameter(Mandatory = $true)]
    [string]$EnvironmentFile,

    [ValidatePattern('^[A-Za-z0-9]+$')]
    [string]$Location = 'westeurope',

    [ValidatePattern('^[a-z_][a-z0-9_-]{0,31}$')]
    [string]$AdminUsername = 'placepulse',

    [ValidatePattern('^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?$')]
    [string]$RepositoryUrl = 'https://github.com/abatamny/place_pulse.git',

    [ValidatePattern('^[A-Za-z0-9._/-]+$')]
    [string]$Branch = 'main',

    [string]$VmSize = 'Standard_B2s'
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI is required. Install it from https://aka.ms/installazurecliwindows.'
}

$resolvedKey = (Resolve-Path -LiteralPath $SshPublicKeyPath).Path
$resolvedEnvironment = (Resolve-Path -LiteralPath $EnvironmentFile).Path
$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$templatePath = Join-Path $repositoryRoot 'deploy\azure\cloud-init.yaml.template'
if (-not (Test-Path -LiteralPath $templatePath -PathType Leaf)) {
    throw "Azure cloud-init template not found: $templatePath"
}

$environmentContent = (Get-Content -Raw -LiteralPath $resolvedEnvironment).TrimEnd()
if (-not $environmentContent) {
    throw 'The Azure environment file cannot be empty.'
}
$environmentContent += "`nAPP_PORT=80`n"
$environmentBase64 = [Convert]::ToBase64String(
    [Text.Encoding]::UTF8.GetBytes($environmentContent)
)

$cloudInit = Get-Content -Raw -LiteralPath $templatePath
$cloudInit = $cloudInit.Replace('__PLACEPULSE_ENV_BASE64__', $environmentBase64)
$cloudInit = $cloudInit.Replace('__PLACEPULSE_REPOSITORY__', $RepositoryUrl)
$cloudInit = $cloudInit.Replace('__PLACEPULSE_BRANCH__', $Branch)

$temporaryPath = Join-Path (
    [IO.Path]::GetTempPath()
) "placepulse-cloud-init-$([guid]::NewGuid().ToString('N')).yaml"
[IO.File]::WriteAllText(
    $temporaryPath,
    $cloudInit,
    [Text.UTF8Encoding]::new($false)
)

try {
    & az account show --output none
    if ($LASTEXITCODE -ne 0) {
        throw 'Sign in first with az login and select the intended subscription.'
    }

    if (-not $PSCmdlet.ShouldProcess(
        "$ResourceGroup/$VmName in $Location",
        'Create an Azure VM and start PlacePulse'
    )) {
        return
    }

    & az group create `
        --name $ResourceGroup `
        --location $Location `
        --output none
    if ($LASTEXITCODE -ne 0) {
        throw 'Azure resource group creation failed.'
    }

    & az vm create `
        --resource-group $ResourceGroup `
        --name $VmName `
        --image Ubuntu2404 `
        --size $VmSize `
        --admin-username $AdminUsername `
        --ssh-key-values $resolvedKey `
        --public-ip-sku Standard `
        --nsg-rule SSH `
        --custom-data $temporaryPath `
        --output none
    if ($LASTEXITCODE -ne 0) {
        throw 'Azure VM creation failed.'
    }

    & az vm open-port `
        --resource-group $ResourceGroup `
        --name $VmName `
        --port 80 `
        --priority 1010 `
        --output none
    if ($LASTEXITCODE -ne 0) {
        throw 'Opening the public web port failed.'
    }

    $publicIp = & az vm show `
        --resource-group $ResourceGroup `
        --name $VmName `
        --show-details `
        --query publicIps `
        --output tsv
    if ($LASTEXITCODE -ne 0 -or -not $publicIp) {
        throw 'The VM was created, but its public IP could not be read.'
    }

    Write-Host "PlacePulse provisioning started at http://$publicIp"
    Write-Host 'Cloud-init may need several minutes to install Docker and build the app.'
}
finally {
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }
}
