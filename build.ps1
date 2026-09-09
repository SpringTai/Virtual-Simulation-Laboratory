param([switch]$SkipArchive)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$environmentPython = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $environmentPython)) { throw 'Build environment is missing.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'main.py'))) { throw 'main.py is missing; integrate the application before building.' }
Push-Location -LiteralPath $projectRoot
try {
    & $environmentPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
    & $environmentPython packaging/write_dependency_manifest.py
    if ($LASTEXITCODE -ne 0) { throw 'Dependency manifest creation failed.' }
    & $environmentPython -m PyInstaller --noconfirm --distpath dist-v2 TensileLab.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    $executable = Join-Path $projectRoot 'dist-v2/TensileLab/TensileLab.exe'
    if (-not (Test-Path -LiteralPath $executable)) { throw 'Packaged executable is missing.' }
    foreach ($filename in @('使用说明.txt', '模型与数据说明.md', '示例_读取实验数据.py', 'README.md', '验收记录.md')) {
        $document = Join-Path $projectRoot $filename
        if (Test-Path -LiteralPath $document) { Copy-Item -LiteralPath $document -Destination (Join-Path $projectRoot 'dist-v2/TensileLab') -Force }
    }
    $releaseRoot = Join-Path $projectRoot 'release-v2'
    New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
    foreach ($filename in @('install.ps1', 'install.cmd', 'uninstall.ps1', 'INSTALL-README.txt')) {
        Copy-Item -LiteralPath (Join-Path $projectRoot "packaging/$filename") -Destination $releaseRoot -Force
    }
    Copy-Item -LiteralPath (Join-Path $projectRoot 'dist-v2/TensileLab') -Destination $releaseRoot -Recurse -Force
    if (-not $SkipArchive) {
        $archive = Join-Path $projectRoot 'MechanicsVirtualLab-v2-Windows-x64-offline.zip'
        Compress-Archive -LiteralPath @((Join-Path $releaseRoot 'TensileLab'), (Join-Path $releaseRoot 'install.ps1'), (Join-Path $releaseRoot 'install.cmd'), (Join-Path $releaseRoot 'uninstall.ps1'), (Join-Path $releaseRoot 'INSTALL-README.txt')) -DestinationPath $archive -Force
        Write-Host "Portable release: $archive"
    }
    Write-Host 'Build created. Functional verification must be performed before delivery.'
}
finally { Pop-Location }
