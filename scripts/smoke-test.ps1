$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    $dockerDesktopBin = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin"
    $dockerDesktopCli = Join-Path $dockerDesktopBin "docker.exe"

    if (Test-Path -LiteralPath $dockerDesktopCli) {
        $env:Path = "$dockerDesktopBin;$env:Path"
    }
}

function Assert-LastExitCode([string]$Action) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Action failed with exit code $LASTEXITCODE."
    }
}

function Invoke-DatabaseQuery([string]$Sql) {
    $dbUser = (& docker compose exec -T db printenv POSTGRES_USER).Trim()
    Assert-LastExitCode "Reading the database user"

    $dbName = (& docker compose exec -T db printenv POSTGRES_DB).Trim()
    Assert-LastExitCode "Reading the database name"

    $result = & docker compose exec -T db psql `
        -v ON_ERROR_STOP=1 `
        -U $dbUser `
        -d $dbName `
        -tAc $Sql
    Assert-LastExitCode "Database query"
    return ($result | Out-String).Trim()
}

function Wait-ForHealth([int]$Attempts = 30) {
    $portBindings = @(& docker compose port web 80)
    Assert-LastExitCode "Reading the public application port"
    $portBinding = $portBindings[0].Trim()

    if ($portBinding -notmatch ":(?<port>\d+)$") {
        throw "Could not determine the public application port from '$portBinding'."
    }

    $port = $Matches.port
    $healthUrl = "http://localhost:$port/api/health"

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
            if ($response.status -eq "ok" -and $response.database -eq "ok") {
                return
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }

    throw "The public health endpoint did not become ready at $healthUrl."
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is required to run the startup smoke test."
}

Write-Host "Building and starting PlacePulse..."
& docker compose up --build -d
Assert-LastExitCode "Docker Compose startup"

Write-Host "Waiting for the public health endpoint..."
Wait-ForHealth

Write-Host "Checking automatic schema creation..."
$tableName = Invoke-DatabaseQuery "SELECT to_regclass('public.foundation_records');"
if ($tableName -ne "foundation_records") {
    throw "The foundation_records table was not created automatically."
}

Write-Host "Writing a persistence marker..."
Invoke-DatabaseQuery "INSERT INTO foundation_records (record_key, record_value) VALUES ('startup-smoke', 'persists') ON CONFLICT (record_key) DO UPDATE SET record_value = EXCLUDED.record_value;" | Out-Null

Write-Host "Restarting PostgreSQL..."
& docker compose restart db
Assert-LastExitCode "Database restart"
Wait-ForHealth

$value = Invoke-DatabaseQuery "SELECT record_value FROM foundation_records WHERE record_key = 'startup-smoke';"
if ($value -ne "persists") {
    throw "The persistence marker did not survive the database restart."
}

Write-Host "Smoke test passed: startup, health, schema creation, and persistence are working."
