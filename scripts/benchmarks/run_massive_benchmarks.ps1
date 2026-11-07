# Ejecutar en la raiz del repositorio, luego de -mode prepare.
# Ejemplo:
# powershell -ExecutionPolicy Bypass -File scripts/benchmarks/run_massive_benchmarks.ps1
param(
    [int[]]$Workers = @(1, 2, 4, 8),
    [int]$Repeticiones = 3,
    [int]$K = 3,
    [int]$MaxIter = 25,
    [string]$Carpeta = "data/processed/massive_mef"
)

$ErrorActionPreference = "Stop"
if ($Repeticiones -lt 1) { throw "Repeticiones debe ser positivo" }

$exe = if (Test-Path "./massivekmeans.exe") { "./massivekmeans.exe" } else { throw "Compila con: go build -o massivekmeans.exe ./cmd/massivekmeans" }
$rows = @()
foreach ($worker in $Workers) {
    foreach ($r in 1..$Repeticiones) {
        Write-Host "K=$K workers=$worker repeticion=$r"
        & $exe -mode train -k $K -workers $worker -max-iter $MaxIter -seed 42 -out $Carpeta
        if ($LASTEXITCODE -ne 0) { throw "Fallo entrenamiento K=$K workers=$worker" }
        $reportPath = Join-Path $Carpeta "training_k${K}_w${worker}_seed42.json"
        $j = Get-Content $reportPath -Raw | ConvertFrom-Json
        $rows += [PSCustomObject]@{
            K = $K
            Workers = $worker
            Repeticion = $r
            DuracionMs = $j.training_duration_ms
            Inercia = $j.inertia
            Iteraciones = $j.iterations
            Convergio = $j.converged
            Filas = $j.rows
        }
    }
}
$output = Join-Path $Carpeta "benchmarks_massive.csv"
$rows | Export-Csv $output -NoTypeInformation -Encoding UTF8
$rows | Format-Table -AutoSize
Write-Host "Resultados en $output"
# El script no declara ganadores: compare medianas solo entre corridas
# con K, semilla, datos y criterios de convergencia equivalentes.
