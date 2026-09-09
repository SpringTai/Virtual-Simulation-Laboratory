param([switch]$Quiet)
$ErrorActionPreference = 'Stop'
$packageRoot = $PSScriptRoot
$sourceDirectory = Join-Path $packageRoot 'TensileLab'
$sourceExecutable = Join-Path $sourceDirectory 'TensileLab.exe'
if (-not (Test-Path -LiteralPath $sourceExecutable)) { throw 'TensileLab/TensileLab.exe is missing. Extract the complete offline package first.' }
$programsRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Programs'))
$installDirectory = [IO.Path]::GetFullPath((Join-Path $programsRoot 'TensileLab'))
if ($installDirectory -ne (Join-Path $programsRoot 'TensileLab')) { throw 'Invalid installation path.' }
$installationMarker = Join-Path $installDirectory 'installation.json'
if ((Test-Path -LiteralPath (Join-Path $installDirectory 'TensileLab.exe')) -and -not (Test-Path -LiteralPath $installationMarker)) { throw 'The destination contains an unrecognized installation.' }
if (Test-Path -LiteralPath $installationMarker) {
    $previousInstallation = Get-Content -LiteralPath $installationMarker -Raw | ConvertFrom-Json
    if ($previousInstallation.applicationId -ne 'MechanicsVirtualLab.TensileLab') { throw 'The destination belongs to another application.' }
}
$running = Get-Process -Name TensileLab -ErrorAction SilentlyContinue
foreach ($process in $running) {
    if ($process.Path -and $process.Path.StartsWith($installDirectory + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Close the running laboratory before installing an update.' }
}
New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
Get-ChildItem -LiteralPath $sourceDirectory -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $installDirectory -Recurse -Force
}
Copy-Item -LiteralPath (Join-Path $packageRoot 'uninstall.ps1') -Destination $installDirectory -Force
@{applicationId='MechanicsVirtualLab.TensileLab'; version='2.0.0'; installedAt=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $installationMarker -Encoding UTF8
$installedExecutable = Join-Path $installDirectory 'TensileLab.exe'
$desktopDirectory = [Environment]::GetFolderPath('Desktop')
$menuDirectory = [Environment]::GetFolderPath('Programs')
$shortcutLabel = ([char]0x529b).ToString() + [char]0x5b66 + [char]0x865a + [char]0x62df + [char]0x5b9e + [char]0x9a8c + [char]0x5ba4
$shell = New-Object -ComObject WScript.Shell
foreach ($shortcutDirectory in @($desktopDirectory, $menuDirectory)) {
    $shortcut = $shell.CreateShortcut((Join-Path $shortcutDirectory ($shortcutLabel + '.lnk')))
    $shortcut.TargetPath = $installedExecutable
    $shortcut.WorkingDirectory = $installDirectory
    $shortcut.Description = 'Six offline mechanics experiments: tension, compression, torsion, bending, shear and buckling'
    $shortcut.IconLocation = $installedExecutable + ',0'
    $shortcut.Save()
}
$uninstallKey = 'HKCU:/Software/Microsoft/Windows/CurrentVersion/Uninstall/TensileLab'
New-Item -Path $uninstallKey -Force | Out-Null
New-ItemProperty -Path $uninstallKey -Name DisplayName -Value $shortcutLabel -PropertyType String -Force | Out-Null
New-ItemProperty -Path $uninstallKey -Name DisplayVersion -Value '2.0.0' -PropertyType String -Force | Out-Null
New-ItemProperty -Path $uninstallKey -Name InstallLocation -Value $installDirectory -PropertyType String -Force | Out-Null
New-ItemProperty -Path $uninstallKey -Name DisplayIcon -Value $installedExecutable -PropertyType String -Force | Out-Null
$uninstallCommand = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $installDirectory 'uninstall.ps1') + '"'
New-ItemProperty -Path $uninstallKey -Name UninstallString -Value $uninstallCommand -PropertyType String -Force | Out-Null
New-ItemProperty -Path $uninstallKey -Name NoModify -Value 1 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $uninstallKey -Name NoRepair -Value 1 -PropertyType DWord -Force | Out-Null
Write-Host "Installed: $installedExecutable"
if (-not $Quiet) { Write-Host 'The desktop and Start menu shortcuts are ready. No Python installation or Internet connection is needed.' }
