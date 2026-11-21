# Run from repository root, using your installed Go 1.27 toolchain.
$ErrorActionPreference = 'Stop'
if (!(Test-Path 'go.mod')) { throw 'Ejecutar desde la raíz del repositorio (go.mod)' }
& go get 'go.mongodb.org/mongo-driver/v2@v2.9.2' 'github.com/redis/go-redis/v9@v9.23.0'
if ($LASTEXITCODE -ne 0) { throw 'Error al descargar dependencias; revisar conectividad' }
& go mod tidy
if ($LASTEXITCODE -ne 0) { throw 'Error go mod tidy' }
Write-Host 'Go dependencies ready. Commit go.mod and go.sum with PC4.' -ForegroundColor Green
