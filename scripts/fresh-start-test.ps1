[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 18080
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    $dockerDesktopBin = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin'
    $dockerDesktopCli = Join-Path $dockerDesktopBin 'docker.exe'
    if (Test-Path -LiteralPath $dockerDesktopCli) {
        $env:Path = "$dockerDesktopBin;$env:Path"
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker is required to run the fresh-start test.'
}

function Assert-LastExitCode([string]$Action) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Action failed with exit code $LASTEXITCODE."
    }
}

$projectName = "placepulse-step9-$PID"
$previousPort = $env:APP_PORT
$previousAppEnvironment = $env:APP_ENV
$env:APP_PORT = $Port
$env:APP_ENV = 'development'
$baseUrl = "http://localhost:$Port"
$healthUrl = "http://localhost:$Port/api/health"

try {
    Write-Host "Starting isolated Docker project '$projectName' on port $Port..."
    & docker compose --project-name $projectName up --build -d
    Assert-LastExitCode 'Fresh Docker Compose startup'

    $ready = $false
    for ($attempt = 1; $attempt -le 45; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
            if ($health.status -eq 'ok' -and $health.database -eq 'ok') {
                $ready = $true
                break
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }
    if (-not $ready) {
        & docker compose --project-name $projectName ps
        & docker compose --project-name $projectName logs
        throw "The fresh application did not become healthy at $healthUrl."
    }

    $homeResponse = Invoke-WebRequest `
        -UseBasicParsing `
        -Uri "http://localhost:$Port/" `
        -TimeoutSec 5
    if ($homeResponse.Content -notmatch '<title>PlacePulse</title>') {
        throw 'The public web entry point did not return the PlacePulse application.'
    }

    $registration = Invoke-RestMethod `
        -Method Post `
        -Uri "$baseUrl/api/auth/register" `
        -ContentType 'application/json' `
        -Body (@{
            phone = '0500999999'
            nickname = 'Fresh Start User'
            password = 'course-password'
        } | ConvertTo-Json)
    if (-not $registration.verification_code) {
        throw 'The isolated development registration did not return a verification code.'
    }

    Invoke-RestMethod `
        -Method Post `
        -Uri "$baseUrl/api/auth/verify" `
        -ContentType 'application/json' `
        -Body (@{
            phone = '0500999999'
            code = $registration.verification_code
        } | ConvertTo-Json) | Out-Null
    $login = Invoke-RestMethod `
        -Method Post `
        -Uri "$baseUrl/api/auth/login" `
        -ContentType 'application/json' `
        -Body (@{
            phone = '0500999999'
            password = 'course-password'
        } | ConvertTo-Json)
    $authHeaders = @{ Authorization = "Bearer $($login.access_token)" }
    $currentUser = Invoke-RestMethod `
        -Uri "$baseUrl/api/auth/me" `
        -Headers $authHeaders
    if ($currentUser.nickname -ne 'Fresh Start User') {
        throw 'The authenticated request did not return the fresh-start user.'
    }
    Invoke-RestMethod `
        -Method Post `
        -Uri "$baseUrl/api/auth/logout" `
        -Headers $authHeaders | Out-Null

    $runningServices = @(
        & docker compose --project-name $projectName ps --services --status running
    )
    Assert-LastExitCode 'Reading fresh service status'
    if ($runningServices.Count -ne 4) {
        throw "Expected 4 running services, found $($runningServices.Count)."
    }

    Write-Host 'Fresh-start test passed: services, UI, health, and the authenticated proxy flow are ready.'
}
finally {
    Write-Host "Removing isolated Docker project '$projectName' and its test volumes..."
    & docker compose --project-name $projectName down -v --remove-orphans
    if ($null -eq $previousPort) {
        Remove-Item Env:APP_PORT -ErrorAction SilentlyContinue
    }
    else {
        $env:APP_PORT = $previousPort
    }
    if ($null -eq $previousAppEnvironment) {
        Remove-Item Env:APP_ENV -ErrorAction SilentlyContinue
    }
    else {
        $env:APP_ENV = $previousAppEnvironment
    }
}
