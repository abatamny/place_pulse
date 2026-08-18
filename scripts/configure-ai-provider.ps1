param(
    [Parameter(Mandatory = $true)]
    [string]$CredentialFile,
    [string]$Model = "qwen3.7-plus"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $projectRoot ".env"
$templatePath = Join-Path $projectRoot ".env.example"

if (-not (Test-Path -LiteralPath $CredentialFile)) {
    throw "Credential file not found"
}

$values = @{}
Get-Content -LiteralPath $CredentialFile |
    ConvertFrom-Csv -Header Field, Value |
    ForEach-Object { $values[$_.Field] = $_.Value }

$apiKey = [string]$values["apiKey"]
$baseUrl = [string]$values["openAiCompatible"]
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    throw "Credential file does not contain an API key"
}
if (-not $baseUrl.StartsWith("https://")) {
    throw "Credential file does not contain a valid compatible endpoint"
}

$updates = [ordered]@{
    AI_PROVIDER = "openai-compatible"
    AI_API_URL = "$($baseUrl.TrimEnd('/'))/chat/completions"
    AI_API_FORMAT = "chat_completions"
    AI_API_KEY = $apiKey
    AI_MODEL = $Model
    AI_MODERATION_MODEL = $Model
    AI_MEDIA_MODERATION_MODE = "model"
    AI_TIMEOUT_SECONDS = "20"
}

$lines = if (Test-Path -LiteralPath $envPath) {
    @(Get-Content -LiteralPath $envPath)
} else {
    @(Get-Content -LiteralPath $templatePath)
}
$seen = @{}
$output = foreach ($line in $lines) {
    $name = ($line -split "=", 2)[0]
    if ($updates.Contains($name)) {
        $seen[$name] = $true
        "$name=$($updates[$name])"
    } else {
        $line
    }
}
foreach ($name in $updates.Keys) {
    if (-not $seen.ContainsKey($name)) {
        $output += "$name=$($updates[$name])"
    }
}

[System.IO.File]::WriteAllLines(
    $envPath,
    [string[]]$output,
    [System.Text.UTF8Encoding]::new($false)
)

$endpoint = [Uri]$baseUrl
Write-Output "Configured $Model at $($endpoint.Host). The private key was written only to .env."
