param(
    [string]$Python = '',
    [string]$Environment = '.venv-offline'
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$wheelDirectory = Join-Path $projectRoot 'offline_packages'
$lockFile = Join-Path $projectRoot 'requirements-lock.txt'
if (-not (Test-Path -LiteralPath $lockFile)) { throw 'Missing requirements-lock.txt.' }
if (-not (Test-Path -LiteralPath $wheelDirectory)) { throw 'Missing offline_packages.' }
if ([string]::IsNullOrWhiteSpace($Python)) {
    $candidate = Join-Path $projectRoot '.venv/Scripts/python.exe'
    if (Test-Path -LiteralPath $candidate) { $Python = $candidate }
    else { throw 'Pass -Python with a CPython 3.12 x64 executable. The installed desktop application does not require Python.' }
}
& $Python -c "import sys,struct; assert sys.version_info[:2] == (3,12), 'CPython 3.12 required'; assert struct.calcsize('P') == 8, '64-bit Python required'"
if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python.' }
$environmentPath = [IO.Path]::GetFullPath((Join-Path $projectRoot $Environment))
$projectPrefix = [IO.Path]::GetFullPath($projectRoot).TrimEnd('\') + '\'
if (-not $environmentPath.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Environment must be inside the project.' }
if (Test-Path -LiteralPath $environmentPath) { throw 'Environment already exists. Choose a new -Environment name.' }
& $Python -m venv $environmentPath
if ($LASTEXITCODE -ne 0) { throw 'Could not create the environment.' }
$environmentPython = Join-Path $environmentPath 'Scripts/python.exe'
& $environmentPython -m pip install --no-index --find-links $wheelDirectory -r $lockFile
if ($LASTEXITCODE -ne 0) { throw 'Offline dependency installation failed.' }
& $environmentPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency consistency check failed.' }
Write-Host "Offline environment ready: $environmentPath"
