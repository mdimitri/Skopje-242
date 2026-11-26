$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw 'Node.js and npm are required. Install Node.js, then run setup.ps1 again.'
}

if (-not (Test-Path 'node_modules\onnxruntime-web\dist\ort.min.js')) {
    npm install
    if ($LASTEXITCODE -ne 0) { throw 'npm install failed.' }
}

$modelDir = Join-Path $PSScriptRoot 'models'
$modelPath = Join-Path $modelDir 'dinov3s_buildings.onnx'
if (-not (Test-Path $modelPath)) {
    New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
    $modelUri = 'https://huggingface.co/kshitijrajsharma/dinov3-hot-buildings/resolve/main/dinov3s_buildings.onnx'
    $downloadPath = "$modelPath.download"
    $ProgressPreference = 'SilentlyContinue'
    try {
        Invoke-WebRequest -Uri $modelUri -OutFile $downloadPath
        if ((Get-Item $downloadPath).Length -lt 100MB) { throw 'The downloaded model file is incomplete.' }
        Move-Item -LiteralPath $downloadPath -Destination $modelPath
    }
    finally {
        if (Test-Path $downloadPath) { Remove-Item -LiteralPath $downloadPath }
    }
}

Write-Host 'Setup complete. Start the app with start.bat.'
