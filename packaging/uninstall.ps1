$ErrorActionPreference = 'Stop'
$programsRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Programs'))
$installDirectory = [IO.Path]::GetFullPath((Join-Path $programsRoot 'TensileLab'))
$allowedDirectory = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Programs/TensileLab'))
if ($installDirectory -ne $allowedDirectory -or (Split-Path -Leaf $installDirectory) -ne 'TensileLab') { throw 'Refusing an invalid uninstall path.' }
$installationMarker = Join-Path $installDirectory 'installation.json'
if (-not (Test-Path -LiteralPath $installationMarker)) { throw 'This directory is not a recognized laboratory installation.' }
$installation = Get-Content -LiteralPath $installationMarker -Raw | ConvertFrom-Json
if ($installation.applicationId -ne 'MechanicsVirtualLab.TensileLab') { throw 'Refusing to remove another application.' }
$running = Get-Process -Name TensileLab -ErrorAction SilentlyContinue
foreach ($process in $running) {
    if ($process.Path -and $process.Path.StartsWith($installDirectory + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Close the laboratory before uninstalling.' }
}
$shortcutLabel = ([char]0x529b).ToString() + [char]0x5b66 + [char]0x865a + [char]0x62df + [char]0x5b9e + [char]0x9a8c + [char]0x5ba4
foreach ($shortcutDirectory in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $shortcutPath = Join-Path $shortcutDirectory ($shortcutLabel + '.lnk')
    if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath -Force }
}
if (Test-Path -LiteralPath $installDirectory) { Remove-Item -LiteralPath $installDirectory -Recurse -Force }
$uninstallKey = 'HKCU:/Software/Microsoft/Windows/CurrentVersion/Uninstall/TensileLab'
if (Test-Path -LiteralPath $uninstallKey) { Remove-Item -LiteralPath $uninstallKey -Recurse -Force }
Write-Host 'TensileLab has been uninstalled. User experiment exports and caches were preserved.'
