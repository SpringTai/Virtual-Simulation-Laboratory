$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$package = Join-Path $root 'release-v2.1'
$testRoot = Join-Path $root ('verification-output/v2.1/install-test-' + [Guid]::NewGuid().ToString('N'))
$destination = Join-Path $testRoot 'custom path/TensileLab'
New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
& (Join-Path $package 'install.ps1') -Quiet -InstallDirectory $destination -NoShortcuts -NoRegistration
$marker = Get-Content (Join-Path $destination 'installation.json') -Raw | ConvertFrom-Json
if ($marker.installDirectory -ne [IO.Path]::GetFullPath($destination)) { throw 'Incorrect installed location.' }
if ($marker.PSObject.Properties.Name -contains 'publisher' -or $marker.version -ne '2.1.1') { throw 'Unexpected publisher or version.' }
$report = Join-Path $testRoot 'selftest/report.json'
New-Item -ItemType Directory -Path (Split-Path -Parent $report) -Force | Out-Null
$process = Start-Process -FilePath (Join-Path $destination 'TensileLab.exe') -ArgumentList @('--self-test', ('"' + $report + '"')) -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0 -or -not (Get-Content $report -Raw | ConvertFrom-Json).ok) { throw 'Installed application selftest failed.' }
$sentinel = Join-Path $destination 'user-experiment.txt'
[IO.File]::WriteAllText($sentinel, 'preserve user experiment')
$legacyLogo = Join-Path $destination '_internal/assets/logo.jpeg'
[IO.File]::WriteAllText($legacyLogo, 'obsolete installer-owned branding fixture')
$marker.files += '_internal/assets/logo.jpeg'
$marker | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $destination 'installation.json') -Encoding UTF8
& (Join-Path $package 'install.ps1') -Quiet -InstallDirectory $destination -NoShortcuts -NoRegistration
if ([IO.File]::ReadAllText($sentinel) -ne 'preserve user experiment') { throw 'Update overwrote user data.' }
if (Test-Path -LiteralPath $legacyLogo) { throw 'Upgrade retained obsolete branding.' }
# Refuse nonempty unrelated destinations before any installation writes.
$unrelated = Join-Path $testRoot 'unrelated'
New-Item -ItemType Directory -Path $unrelated -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $unrelated 'keep.txt'), 'keep')
$rejected = $false
try { & (Join-Path $package 'install.ps1') -Quiet -InstallDirectory $unrelated -NoShortcuts -NoRegistration } catch { $rejected = $true }
if (-not $rejected -or (Test-Path (Join-Path $unrelated 'TensileLab.exe'))) { throw 'Unrelated folder was not protected.' }
# The target is a uniquely created test installation inside this workspace.
$resolved = [IO.Path]::GetFullPath($destination)
if (-not $resolved.StartsWith([IO.Path]::GetFullPath($testRoot) + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected test uninstall target.' }
& (Join-Path $destination 'uninstall.ps1')
if ((Test-Path (Join-Path $destination 'TensileLab.exe')) -or -not (Test-Path $sentinel)) { throw 'Uninstall preservation failed.' }
@{passed=$true;customPath=$destination;installedSelftest=$report;upgradePreservedUserData=$true;uninstallPreservedUserData=$true;nonemptyFolderRejected=$true} | ConvertTo-Json | Set-Content (Join-Path $testRoot 'installation-report.json') -Encoding UTF8
Write-Host "Installation verification passed: $testRoot"
$accepted = Join-Path $root 'verification-output/v2.1/installed'
New-Item -ItemType Directory -Path $accepted -Force | Out-Null
Copy-Item -LiteralPath $report -Destination (Join-Path $accepted 'report.json') -Force
Copy-Item -LiteralPath (Join-Path $testRoot 'installation-report.json') -Destination $accepted -Force
