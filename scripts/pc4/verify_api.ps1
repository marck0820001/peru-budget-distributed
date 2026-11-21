# Run from repository root AFTER: docker compose -f compose.pc4.api.yaml up -d --build
param([switch]$RunTraining, [string]$BaseUrl = 'http://localhost:8080')
$ErrorActionPreference = 'Stop'
$base = $BaseUrl.TrimEnd('/')
Write-Host '=== HTTP /health ===' -ForegroundColor Cyan
$health = Invoke-RestMethod -Uri "$base/health" -Method Get
$health | ConvertTo-Json -Depth 5
if ($health.status -ne 'ok') { throw 'API no saludable' }
Write-Host '=== Nodos TCP ===' -ForegroundColor Cyan
$nodes = Invoke-RestMethod -Uri "$base/api/v1/cluster/nodes" -Method Get
$nodes | ConvertTo-Json -Depth 5
if (($nodes.nodes | Where-Object {-not $_.reachable}).Count -gt 0) {
    throw 'Al menos un nodo TCP no esta accesible; revisa los logs antes de entrenar'
}
Write-Host 'Swagger: http://localhost:8080/docs' -ForegroundColor Green
Write-Host 'OpenAPI: http://localhost:8080/openapi.yaml' -ForegroundColor Green
if (-not $RunTraining) { Write-Host 'Pruebas HTTP basicas OK. Usa -RunTraining para iniciar K-Means.'; exit 0 }

Write-Host '=== Iniciando K-Means distribuido K=3, seed=42 ===' -ForegroundColor Cyan
$body = @{ k = 3; seed = 42; max_iterations = 25 } | ConvertTo-Json -Compress
$created = Invoke-RestMethod -Uri "$base/api/v1/train" -Method Post -ContentType 'application/json' -Body $body
$id = $created.job_id
if ([string]::IsNullOrEmpty($id)) { throw 'La API no devolvio job_id' }
Write-Host "Trabajo creado: $id"
$deadline = (Get-Date).AddMinutes(15)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    $job = Invoke-RestMethod -Uri "$base/api/v1/jobs/$id" -Method Get
    Write-Host "Estado=$($job.status); job=$id"
    if ($job.status -eq 'failed') { throw "Entrenamiento fallo: $($job.error)" }
    if ($job.status -eq 'succeeded') { break }
}
if ($job.status -ne 'succeeded') { throw 'Timeout esperando el entrenamiento' }
New-Item -ItemType Directory -Path 'data/processed/pc4_api' -Force | Out-Null
$summary = "data/processed/pc4_api/estado_$id.json"
$job | ConvertTo-Json -Depth 12 | Set-Content -Path $summary -Encoding UTF8
$report = "data/processed/pc4_api/reporte_api_$id.json"
Invoke-WebRequest -Uri "$base/api/v1/jobs/$id/result" -OutFile $report
Write-Host "Entrenamiento finalizado. Estado: $summary" -ForegroundColor Green
Write-Host "Reporte: $report" -ForegroundColor Green
Write-Host "Inercia=$($job.inertia); iteraciones=$($job.iterations); clusters=$($job.cluster_sizes -join ',')"
