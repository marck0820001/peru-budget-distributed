<#
.SYNOPSIS
  Benchmark reproducible de consultas HTTP de PeruBudget PC4.
.DESCRIPTION
  Realiza warm-up y N solicitudes GET por endpoint. No inicia entrenamientos.
  Registra latencia de extremo a extremo desde PowerShell y estado HTTP.
  Genera detalles CSV, resumen CSV y JSON para las evidencias de PC4.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts/pc4/benchmark_http.ps1 -Iterations 50
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 10000)]
    [int]$Iterations = 50,

    [ValidateRange(0, 1000)]
    [int]$Warmup = 3,

    [string]$BaseUrl = 'http://localhost:8080',

    [string]$JobId = '24723f15a506976bbbcb2ceb',

    [string]$OutputDirectory = 'docs/evidence/pc4'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$base = $BaseUrl.TrimEnd('/')
$endpoints = [ordered]@{
    health  = "$base/health"
    storage = "$base/api/v1/storage/health"
    nodes   = "$base/api/v1/cluster/nodes"
    job     = "$base/api/v1/jobs/$JobId"
    result  = "$base/api/v1/jobs/$JobId/result"
}

function Invoke-BenchmarkRequest {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [Parameter(Mandatory = $true)][int]$Iteration
    )

    $statusCode = 0
    $errorMessage = ''
    $startTimeUtc = (Get-Date).ToUniversalTime().ToString('o')
    $watch = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        $response = Invoke-WebRequest -Method Get -Uri $Url -TimeoutSec 15 -UseBasicParsing -ErrorAction Stop
        $statusCode = [int]$response.StatusCode
    }
    catch {
        $errorMessage = $_.Exception.Message
        $responseProperty = $_.Exception.PSObject.Properties['Response']
        if ($null -ne $responseProperty -and $null -ne $responseProperty.Value) {
            $statusCode = [int]$responseProperty.Value.StatusCode
        }
    }
    finally {
        $watch.Stop()
    }

    $latencyMs = [math]::Round($watch.Elapsed.TotalMilliseconds, 3)
    [PSCustomObject]@{
        TimestampUtc = $startTimeUtc
        Endpoint = $Endpoint
        Iteration = $Iteration
        StatusCode = $statusCode
        LatencyMs = $latencyMs
        Under100Ms = ($statusCode -eq 200 -and $latencyMs -lt 100)
        Error = $errorMessage
    }
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

Write-Host "=== PeruBudget PC4 | Benchmark de latencias HTTP ==="
Write-Host "URL base: $base"
Write-Host "Job ID: $JobId"
Write-Host "Endpoints: $($endpoints.Count) | Iteraciones: $Iterations | Calentamiento: $Warmup"

# Calentamiento separado de las mediciones, para evitar contabilizar
# la primera apertura de conexion como una solicitud representativa.
for ($i = 1; $i -le $Warmup; $i++) {
    foreach ($endpoint in $endpoints.GetEnumerator()) {
        $null = Invoke-BenchmarkRequest -Url $endpoint.Value -Endpoint $endpoint.Key -Iteration 0
    }
}

$records = New-Object 'System.Collections.Generic.List[object]'
for ($i = 1; $i -le $Iterations; $i++) {
    foreach ($endpoint in $endpoints.GetEnumerator()) {
        $item = Invoke-BenchmarkRequest -Url $endpoint.Value -Endpoint $endpoint.Key -Iteration $i
        $records.Add($item)
        if ($item.StatusCode -ne 200) {
            Write-Warning "Solicitud fallida: $($item.Endpoint), iteracion=$i, HTTP=$($item.StatusCode)"
        }
    }
    Write-Progress -Activity 'Benchmark PC4' -Status "$i/$Iterations iteraciones" -PercentComplete (($i / $Iterations) * 100)
}
Write-Progress -Activity 'Benchmark PC4' -Completed

$detailPath = Join-Path $OutputDirectory 'latencias_http_detalle.csv'
$summaryPath = Join-Path $OutputDirectory 'latencias_http_resumen.csv'
$jsonPath = Join-Path $OutputDirectory 'latencias_http_resumen.json'

$records | Export-Csv -Path $detailPath -NoTypeInformation -Encoding UTF8

$summary = @(
    foreach ($group in ($records | Group-Object Endpoint)) {
        $all = @($group.Group)
        $valid = @($all | Where-Object { $_.StatusCode -eq 200 } | Sort-Object LatencyMs)
        $successful = $valid.Count
        $total = $all.Count
        $under100 = @($all | Where-Object { $_.Under100Ms }).Count
        $errors = $total - $successful

        if ($successful -eq 0) {
            [PSCustomObject]@{
                Endpoint = $group.Name; Requests = $total; HTTP200 = 0; Errors = $errors
                Under100 = 0; CompliancePct = 0; MedianMs = $null; P95Ms = $null; MaxMs = $null
            }
            continue
        }

        if (($successful % 2) -eq 0) {
            $median = ($valid[($successful / 2) - 1].LatencyMs + $valid[$successful / 2].LatencyMs) / 2
        }
        else {
            $middleIndex = [int][math]::Floor($successful / 2)
            $median = $valid[$middleIndex].LatencyMs
        }
        $p95Index = [int][math]::Ceiling($successful * 0.95) - 1

        [PSCustomObject]@{
            Endpoint = $group.Name
            Requests = $total
            HTTP200 = $successful
            Errors = $errors
            Under100 = $under100
            CompliancePct = [math]::Round(100 * $under100 / $total, 2)
            MedianMs = [math]::Round($median, 3)
            P95Ms = [math]::Round($valid[$p95Index].LatencyMs, 3)
            MaxMs = [math]::Round($valid[$successful - 1].LatencyMs, 3)
        }
    }
)

$summary | Export-Csv -Path $summaryPath -NoTypeInformation -Encoding UTF8
[PSCustomObject]@{
    measured_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    base_url = $base
    job_id = $JobId
    iterations = $Iterations
    warmup_per_endpoint = $Warmup
    measurement = 'Client-side end-to-end HTTP latency using PowerShell Invoke-WebRequest; excludes warmup'
    endpoint_summary = $summary
} | ConvertTo-Json -Depth 6 | Set-Content -Path $jsonPath -Encoding UTF8

Write-Host "`n=== Resumen ==="
$summary | Format-Table -AutoSize
Write-Host "`nArchivos generados:"
Write-Host "  $detailPath"
Write-Host "  $summaryPath"
Write-Host "  $jsonPath"
Write-Host 'Nota: la validacion en Postman Collection Runner debe conservarse como evidencia adicional.'
