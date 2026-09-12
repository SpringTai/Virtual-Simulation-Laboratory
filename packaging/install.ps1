param([switch]$Quiet, [string]$InstallDirectory, [switch]$NoShortcuts, [switch]$NoRegistration)
$ErrorActionPreference = 'Stop'
$sourceDirectory = Join-Path $PSScriptRoot 'TensileLab'
if (-not (Test-Path -LiteralPath (Join-Path $sourceDirectory 'TensileLab.exe'))) { throw 'Extract the complete package first.' }
$defaultDirectory = Join-Path $env:LOCALAPPDATA 'Programs/TensileLab'
$key = 'HKCU:/Software/Microsoft/Windows/CurrentVersion/Uninstall/TensileLab'
$registered = Get-ItemProperty $key -ErrorAction SilentlyContinue
if ($registered.InstallLocation) { $defaultDirectory = $registered.InstallLocation }
if (-not $InstallDirectory -and -not $Quiet) {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = '请选择安装位置。程序将安装到所选目录下的 TensileLab 文件夹。'
    $dialog.SelectedPath = Split-Path -Parent $defaultDirectory
    $dialog.ShowNewFolderButton = $true
    try {
        if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { Write-Host 'Installation cancelled.'; exit 2 }
        $InstallDirectory = Join-Path $dialog.SelectedPath 'TensileLab'
    } finally { $dialog.Dispose() }
}
if (-not $InstallDirectory) { $InstallDirectory = $defaultDirectory }
$installDirectory = [IO.Path]::GetFullPath($InstallDirectory).TrimEnd('\')
if ($installDirectory -eq [IO.Path]::GetPathRoot($installDirectory).TrimEnd('\') -or
    $installDirectory -eq [IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd('\') -or
    $installDirectory -eq [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\') -or
    $installDirectory.StartsWith([IO.Path]::GetFullPath($sourceDirectory).TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or
    $installDirectory -eq [IO.Path]::GetFullPath($sourceDirectory).TrimEnd('\')) { throw 'Choose a dedicated application directory outside the package.' }
$marker = Join-Path $installDirectory 'installation.json'
$probe = $installDirectory
while ($probe) {
    if ((Test-Path -LiteralPath $probe) -and ((Get-Item -LiteralPath $probe -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Choose a directory without symbolic links or junctions.' }
    $probe = Split-Path -Parent $probe
}
if ((Test-Path -LiteralPath $installDirectory) -and -not (Test-Path -LiteralPath $marker) -and
    @(Get-ChildItem -LiteralPath $installDirectory -Force).Count -gt 0) { throw 'Choose an empty folder or a recognized laboratory installation.' }
$previous = $null
if (Test-Path -LiteralPath $marker) {
    $previous = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
    if ($previous.applicationId -ne 'MechanicsVirtualLab.TensileLab') { throw 'The destination belongs to another application.' }
}
foreach ($process in (Get-Process -Name TensileLab -ErrorAction SilentlyContinue)) {
    if ($process.Path -and $process.Path.StartsWith($installDirectory + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Close the laboratory before updating.' }
}
New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
Get-ChildItem -LiteralPath $sourceDirectory -Force | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $installDirectory -Recurse -Force }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'uninstall.ps1') -Destination $installDirectory -Force
$ownedFiles = @(Get-ChildItem -LiteralPath $sourceDirectory -Recurse -File | ForEach-Object { $_.FullName.Substring($sourceDirectory.Length+1) }) + @('uninstall.ps1')
if ($previous.files) { $ownedFiles += $previous.files }
# Remove only obsolete branding assets recorded as owned by the previous installer.
foreach ($obsolete in @('_internal/assets/logo.jpeg', '_internal/assets/lab.ico')) {
    if (@($previous.files | Where-Object { $_ -is [string] } | ForEach-Object { $_.Replace('\','/') }) -contains $obsolete) {
        $obsoletePath = Join-Path $installDirectory $obsolete
        if (Test-Path -LiteralPath $obsoletePath -PathType Leaf) { Remove-Item -LiteralPath $obsoletePath -Force }
    }
}
@{applicationId='MechanicsVirtualLab.TensileLab'; version='2.1.1'; publisher='云南数美汇云软件有限公司'; installDirectory=$installDirectory; files=@($ownedFiles | Sort-Object -Unique); installedAt=(Get-Date).ToString('o')} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $marker -Encoding UTF8
$executable = Join-Path $installDirectory 'TensileLab.exe'
$label = ([char]0x529b).ToString() + [char]0x5b66 + [char]0x865a + [char]0x62df + [char]0x5b9e + [char]0x9a8c + [char]0x5ba4
if (-not $NoShortcuts) {
    $shell = New-Object -ComObject WScript.Shell
    foreach ($directory in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
        $shortcut = $shell.CreateShortcut((Join-Path $directory ($label + '.lnk')))
        $shortcut.TargetPath = $executable
        $shortcut.WorkingDirectory = $installDirectory
        $shortcut.IconLocation = $executable + ',0'
        $shortcut.Save()
    }
}
if (-not $NoRegistration) {
    New-Item -Path $key -Force | Out-Null
    $entries = @{DisplayName=$label; DisplayVersion='2.1.1'; Publisher='云南数美汇云软件有限公司'; InstallLocation=$installDirectory; DisplayIcon=$executable;
        UninstallString=('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $installDirectory 'uninstall.ps1') + '"')}
    foreach ($name in $entries.Keys) { New-ItemProperty -Path $key -Name $name -Value $entries[$name] -PropertyType String -Force | Out-Null }
    foreach ($name in @('NoModify','NoRepair')) { New-ItemProperty -Path $key -Name $name -Value 1 -PropertyType DWord -Force | Out-Null }
}
Write-Host "Installed: $executable"
