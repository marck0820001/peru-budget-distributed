<#
 Corre TODO el Entregable 1 (PC3) sobre los CSV oficiales y regenera el informe Word.
 Desde la raíz del repo:   powershell -ExecutionPolicy Bypass -File scripts/run_pc3_all.ps1

 Requisitos: Go 1.22+, Python (py) con  py -m pip install python-docx matplotlib numpy
 CSV en data/raw/:  2024-Gasto-Devengado.csv  y  2025-Gasto-Devengado-Mensual.csv
 Opciones:  -SkipAudit (omite el benchmark de la auditoría, ~5 min)
            -SkipMassive (omite el K-Means de 3.64 M líneas)
            -Workers 8 (workers para ETL y entrenamiento; por defecto, los núcleos lógicos)
 Tiempo total aproximado: 15-25 min. Cierra otros programas pesados para medir bien.
#>
param([int]$Workers = [Environment]::ProcessorCount, [switch]$SkipAudit, [switch]$SkipMassive)
$ErrorActionPreference = "Continue"
function Step($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { Write-Host "FALLÓ: $what" -ForegroundColor Red; exit 1 } }

$logs = "data/processed/logs"; $bench = "data/processed/benchmarks"
New-Item -ItemType Directory -Force $logs, $bench, "bin" | Out-Null
$y24 = Get-ChildItem data/raw -Filter "2024-Gasto-Devengado*.csv" -ErrorAction SilentlyContinue
$y25 = Get-ChildItem data/raw -Filter "2025-Gasto-Devengado*.csv" -ErrorAction SilentlyContinue
if (-not $y24 -or -not $y25) { Write-Host "Faltan los CSV en data/raw/ (2024-Gasto-Devengado*.csv y 2025-Gasto-Devengado*.csv)" -ForegroundColor Red; exit 1 }
go version | Tee-Object "$logs/go_version.txt"
Write-Host "Núcleos lógicos: $([Environment]::ProcessorCount) · workers = $Workers"

Step "1/7 go vet y pruebas (con detector de carreras si hay gcc)"
go vet ./...; Check "go vet"
go test -race -v ./internal/... 2>&1 | Tee-Object "$logs/go_test_full.txt" | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Host "go test -race falló (¿falta gcc para -race en Windows?). Reintento sin -race..." -ForegroundColor Yellow
  go test -v ./internal/... 2>&1 | Tee-Object "$logs/go_test_full.txt" | Out-Null; Check "go test"
}
Select-String -Path "$logs/go_test_full.txt" -Pattern '^(--- |ok |FAIL|PASS)' | ForEach-Object { $_.Line } | Set-Content "$logs/go_test.txt"
Get-Content "$logs/go_test.txt" | Select-Object -Last 8

Step "2/7 Parte A: ETL concurrente (etlgo) con $Workers workers"
go run ./cmd/etlgo --data-dir data/raw --workers $Workers 2>&1 | Tee-Object "$logs/etl.txt"; Check "etlgo"

Step "3/7 Parte B: K-Means MapReduce (mrtrainer)"
go run ./cmd/mrtrainer --in data/processed/go_etl --workers $Workers 2>&1 | Tee-Object "$logs/trainer.txt"; Check "mrtrainer"

Step "4/7 Benchmarks: ETL y K-Means con 1/2/4/8 workers (mediana de 3)"
go run ./cmd/benchmark --data-dir data/raw --workers 1,2,4,8 2>&1 | Tee-Object "$logs/bench.log"; Check "benchmark"
go test -run '^$' -bench . -benchmem ./internal/ingestion ./internal/ml/kmeansmr 2>&1 | Tee-Object "$logs/bench.txt" | Out-Null

if (-not $SkipAudit) {
  Step "5/7 Benchmark de la auditoría de Marco (cmd/etl, lector CSV único)"
  go build -o bin/etl.exe ./cmd/etl; Check "build etl"
  $rows = @()
  foreach ($w in 1, 2, 4, 8) { foreach ($r in 1..3) {
    $t = (Measure-Command { & ./bin/etl.exe -workers $w -out "data/processed/go_ingestion/tmp_auditoria.json" | Out-Null }).TotalSeconds
    Write-Host ("workers={0} rep={1} {2:N3}s" -f $w, $r, $t)
    $rows += [PSCustomObject]@{ Workers = $w; Repeticion = $r; Segundos = [math]::Round($t, 3) }
  } }
  $rows | Export-Csv "$bench/benchmarks_etl.csv" -NoTypeInformation -Encoding UTF8
} else { Step "5/7 (omitido) benchmark de la auditoría" }

if (-not $SkipMassive) {
  Step "6/7 K-Means masivo sobre 3.64 M líneas (Marco)"
  go build -o massivekmeans.exe ./cmd/massivekmeans; Check "build massivekmeans"
  go build -o massiveprofile.exe ./cmd/massiveprofile; Check "build massiveprofile"
  ./massivekmeans.exe -mode prepare -expect-rows 3642510 2>&1 | Tee-Object "$logs/massive_prepare.txt"; Check "massive prepare"
  powershell -ExecutionPolicy Bypass -File scripts/benchmarks/run_massive_benchmarks.ps1 2>&1 | Tee-Object "$logs/massive_bench.txt"; Check "massive benchmark"
  ./massiveprofile.exe -out data/processed/massive_mef -report training_k3_w4_seed42.json -workers 4 2>&1 | Tee-Object "$logs/massive_profile.txt"; Check "massive profile"
} else { Step "6/7 (omitido) K-Means masivo" }

Step "7/7 Informe Word con las cifras reales"
git log --oneline --graph --all 2>&1 | Select-Object -First 30 | Set-Content "$logs/git.txt"
$auditArg = if (Test-Path "$bench/benchmarks_etl.csv") { "$bench/benchmarks_etl.csv" } else { "benchmarks_etl.csv" }
py scripts/report/build_pc3_report.py --audit-bench $auditArg; Check "informe"
Write-Host "`nListo. Informe en docs/reports/ ; resultados en data/processed/" -ForegroundColor Green
