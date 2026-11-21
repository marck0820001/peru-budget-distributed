# PC4 etapa 3: invocar desde la raiz del repositorio con PowerShell.
param(
  [switch]$RunTraining,
  [switch]$CheckRestart,
  [string]$BaseUrl = 'http://localhost:8080'
)
$ErrorActionPreference = 'Stop'
$base = $BaseUrl.TrimEnd('/')

function Wait-Storage {
  for ($i = 0; $i -lt 40; $i++) {
    try {
      $health = Invoke-RestMethod -Method Get -Uri "$base/api/v1/storage/health" -TimeoutSec 4
      if ($health.mongodb -eq 'ok' -and $health.redis -eq 'ok') { return $health }
    } catch { Start-Sleep -Seconds 2 }
  }
  throw 'No se pudo consultar MongoDB/Redis. Revisa docker compose logs api mongodb redis.'
}

Write-Host '=== Persistencia MongoDB + Redis ===' -ForegroundColor Cyan
$health = Wait-Storage
$health | ConvertTo-Json
$nodes = Invoke-RestMethod -Uri "$base/api/v1/cluster/nodes" -Method Get
if (($nodes.nodes | Where-Object { -not $_.reachable }).Count -gt 0) { throw 'Nodo TCP sin conexion' }
Write-Host 'Nodos TCP OK' -ForegroundColor Green

if (-not $RunTraining) {
  Write-Host 'MongoDB y Redis disponibles. Para verificar la persistencia real usa -RunTraining -CheckRestart.'
  exit 0
}

$payload = @{ k = 3; seed = 42; max_iterations = 25 } | ConvertTo-Json -Compress
$created = Invoke-RestMethod -Method Post -Uri "$base/api/v1/train" -ContentType 'application/json' -Body $payload
$id = $created.job_id
if (-not $id) { throw 'La API no devolvio un job_id' }
Write-Host "Job persistido: $id"

$deadline = (Get-Date).AddMinutes(15)
$job = $null
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 2
  $job = Invoke-RestMethod -Method Get -Uri "$base/api/v1/jobs/$id"
  Write-Host "Job=$id Status=$($job.status)"
  if ($job.status -eq 'failed') { throw "Fallo entrenamiento: $($job.error)" }
  if ($job.status -eq 'succeeded') { break }
}
if ($null -eq $job -or $job.status -ne 'succeeded') { throw 'Entrenamiento no finalizo dentro del plazo de comprobacion' }
if ($job.dataset_rows -ne 3642510) { throw "Filas inesperadas: $($job.dataset_rows)" }
if ($job.cluster_sizes.Count -ne 3) { throw 'Tamanos de cluster inesperados' }

New-Item -ItemType Directory -Path 'data/processed/pc4_api' -Force | Out-Null
$job | ConvertTo-Json -Depth 12 | Set-Content -Path "data/processed/pc4_api/estado_storage_$id.json" -Encoding UTF8
Invoke-WebRequest -Uri "$base/api/v1/jobs/$id/result" -OutFile "data/processed/pc4_api/reporte_storage_$id.json"
Write-Host "Informe guardado; inercia=$($job.inertia); iteraciones=$($job.iterations)" -ForegroundColor Green

if ($CheckRestart) {
  Write-Host '=== Reiniciando SOLO la API; preservando volúmenes y nodos ===' -ForegroundColor Cyan
  & docker compose -f compose.pc4.storage.yaml restart api
  if ($LASTEXITCODE -ne 0) { throw 'docker compose restart api fallo' }
  $health = Wait-Storage
  $restored = Invoke-RestMethod -Method Get -Uri "$base/api/v1/jobs/$id"
  if ($restored.status -ne 'succeeded' -or $restored.inertia -ne $job.inertia) {
    throw "El job no fue restaurado correctamente desde MongoDB. Estado=$($restored.status)"
  }
  Invoke-WebRequest -Uri "$base/api/v1/jobs/$id/result" -OutFile "data/processed/pc4_api/reporte_recuperado_$id.json"
  Write-Host 'PASS: MongoDB conserva job e inercia despues de reiniciar la API.' -ForegroundColor Green
}
Write-Host "Job ID: $id" -ForegroundColor Green
Write-Host 'OK: comprobar tambien docker compose logs api mongodb redis.' -ForegroundColor Green
