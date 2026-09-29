# Gera .build/layer/python com as dependências da Lambda (requirements.txt),
# baixando os pacotes compilados para Linux x86_64 -- que é onde a Lambda
# roda, mesmo que você esteja no Windows.
#
# Uso (na pasta terraform):
#   powershell -ExecutionPolicy Bypass -File .\build_layer.ps1

$ErrorActionPreference = "Stop"

$destino = Join-Path $PSScriptRoot ".build\layer\python"
$requirements = Join-Path $PSScriptRoot "..\requirements.txt"

if (Test-Path $destino) { Remove-Item -Recurse -Force $destino }

python -m pip install `
    -r $requirements `
    --platform manylinux2014_x86_64 `
    --implementation cp `
    --python-version 3.13 `
    --only-binary=:all: `
    --target $destino `
    --upgrade

if ($LASTEXITCODE -ne 0) { throw "pip install falhou" }

Write-Host "Layer gerada em $destino"
