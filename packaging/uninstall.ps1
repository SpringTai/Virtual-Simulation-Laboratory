$ErrorActionPreference = 'Stop'
$installDirectory = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$marker = Join-Path $installDirectory 'installation.json'
if (-not (Test-Path -LiteralPath $marker)) { throw 'No recognized installation marker.' }
$installation = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
if ($installation.applicationId -ne 'MechanicsVirtualLab.TensileLab' -or -not $installation.files -or
    $installation.installDirectory -ne $installDirectory) { throw 'Installation path or file manifest is invalid.' }
if ($installDirectory -eq [IO.Path]::GetPathRoot($installDirectory).TrimEnd('\') -or
    $installDirectory -eq [IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd('\')) { throw 'Unsafe uninstall location.' }
$targets = @($installation.files) + @('installation.json') | ForEach-Object {
    $target = [IO.Path]::GetFullPath((Join-Path $installDirectory $_))
    if (-not $target.StartsWith($installDirectory + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid manifest path.' }
    $probe = $target
    while ($probe -and $probe.Length -ge $installDirectory.Length) {
        if (Test-Path -LiteralPath $probe) {
            if ((Get-Item -LiteralPath $probe -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Uninstall refuses linked paths.' }
        }
        $probe = Split-Path -Parent $probe
    }
    $target
}
foreach ($process in (Get-Process -Name TensileLab -ErrorAction SilentlyContinue)) {
    if ($process.Path -and $process.Path.StartsWith($installDirectory + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Close the laboratory before uninstalling.' }
}
$shell = New-Object -ComObject WScript.Shell
$label = ([char]0x529b).ToString() + [char]0x5b66 + [char]0x865a + [char]0x62df + [char]0x5b9e + [char]0x9a8c + [char]0x5ba4
foreach ($directory in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $shortcut = Join-Path $directory ($label + '.lnk')
    if ((Test-Path -LiteralPath $shortcut) -and $shell.CreateShortcut($shortcut).TargetPath -eq (Join-Path $installDirectory 'TensileLab.exe')) { Remove-Item -LiteralPath $shortcut -Force }
}
$key = 'HKCU:/Software/Microsoft/Windows/CurrentVersion/Uninstall/TensileLab'
$registration = Get-ItemProperty $key -ErrorAction SilentlyContinue
if ($registration.InstallLocation -eq $installDirectory) { Remove-Item -LiteralPath $key -Recurse -Force }
foreach ($target in $targets) {
    if (Test-Path -LiteralPath $target -PathType Leaf) { Remove-Item -LiteralPath $target -Force }
}
Get-ChildItem -LiteralPath $installDirectory -Directory -Recurse | Sort-Object { $_.FullName.Length } -Descending | ForEach-Object {
    if (-not (Get-ChildItem -LiteralPath $_.FullName -Force)) { Remove-Item -LiteralPath $_.FullName }
}
if (-not (Get-ChildItem -LiteralPath $installDirectory -Force)) { Remove-Item -LiteralPath $installDirectory }
Write-Host 'Application files removed. User files and experiment caches preserved.'
