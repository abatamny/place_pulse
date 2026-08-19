param(
    [ValidateRange(-90, 90)]
    [double]$Latitude = 31.778,

    [ValidateRange(-180, 180)]
    [double]$Longitude = 35.235
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    $dockerDesktopBin = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin"
    $dockerDesktopCli = Join-Path $dockerDesktopBin "docker.exe"

    if (Test-Path -LiteralPath $dockerDesktopCli) {
        $env:Path = "$dockerDesktopBin;$env:Path"
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is required to run the Overpass smoke test."
}

$latitudeText = $Latitude.ToString([Globalization.CultureInfo]::InvariantCulture)
$longitudeText = $Longitude.ToString([Globalization.CultureInfo]::InvariantCulture)
$query = "[out:json][timeout:20];is_in($latitudeText,$longitudeText)->.areas;(way(pivot.areas)[`"name`"];rel(pivot.areas)[`"name`"];);out tags center;"
$responseText = & docker compose exec -T overpass curl `
    --noproxy "*" `
    -sSf `
    --data-urlencode "data=$query" `
    http://localhost/api/interpreter

if ($LASTEXITCODE -ne 0) {
    throw "The internal Overpass API request failed. Check 'docker compose logs overpass'."
}

try {
    $response = ($responseText | Out-String) | ConvertFrom-Json
}
catch {
    throw "The internal Overpass API returned invalid JSON: $($_.Exception.Message)"
}

$namedElements = @($response.elements | Where-Object { $_.tags.name })
if ($namedElements.Count -eq 0) {
    throw "Overpass returned no named containing features for $Latitude,$Longitude. Area generation may still be running, or the coordinate may not be covered."
}

Write-Host "Local Overpass is ready. Named containing features:"
$namedElements | ForEach-Object {
    Write-Host "- $($_.type)/$($_.id): $($_.tags.name)"
}

Write-Host "Checking backend-to-Overpass resolution..."
$backendCheck = "from app.osm import OSMPlaceResolver; places = OSMPlaceResolver().resolve($latitudeText, $longitudeText); assert places, 'No usable non-administrative place was resolved'; print('\n'.join(f'{place.osm_type}/{place.osm_id}: {place.name}' for place in places))"
$backendResult = & docker compose exec -T backend python -c $backendCheck

if ($LASTEXITCODE -ne 0) {
    throw "The backend could not resolve this coordinate through the internal Overpass API."
}

Write-Host "Backend resolution succeeded:"
$backendResult | ForEach-Object { Write-Host "- $_" }
