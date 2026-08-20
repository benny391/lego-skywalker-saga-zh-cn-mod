param([string]$GamePath = "")

$ErrorActionPreference = "Stop"
$BackupName = "_SimplifiedChineseMod_Backup"

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Restart-Elevated {
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if ($GamePath) { $arguments += " -GamePath `"$GamePath`"" }
    $process = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $arguments -Wait -PassThru
    exit $process.ExitCode
}
function Get-Sha256([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant() }
function Find-GamePath([string]$Requested, $Manifest) {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($Requested) { $candidates.Add($Requested) | Out-Null }
    $roots = @("C:\Program Files (x86)\Steam", "C:\Program Files\Steam")
    foreach ($registryPath in @(
        "HKCU:\Software\Valve\Steam",
        "HKLM:\SOFTWARE\WOW6432Node\Valve\Steam",
        "HKLM:\SOFTWARE\Valve\Steam"
    )) {
        try {
            $item = Get-ItemProperty -Path $registryPath
            if ($item.SteamPath) { $roots += $item.SteamPath }
            if ($item.InstallPath) { $roots += $item.InstallPath }
        } catch {}
    }
    foreach ($root in ($roots | Where-Object { $_ } | Select-Object -Unique)) {
        $candidates.Add((Join-Path $root "steamapps\common\$($Manifest.gameDirectoryName)")) | Out-Null
        $vdf = Join-Path $root "steamapps\libraryfolders.vdf"
        if (Test-Path -LiteralPath $vdf) {
            $content = Get-Content -LiteralPath $vdf -Raw
            foreach ($match in [regex]::Matches($content, '"path"\s+"([^"]+)"')) {
                $library = $match.Groups[1].Value -replace '\\\\', '\'
                $candidates.Add((Join-Path $library "steamapps\common\$($Manifest.gameDirectoryName)")) | Out-Null
            }
        }
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-Path -LiteralPath (Join-Path $candidate $Manifest.gameExecutable)) { return (Resolve-Path $candidate).Path }
    }
    throw "Game installation was not found. Run: Uninstall.cmd <full game path>"
}

try {
    if (-not (Test-Administrator) -and $env:LSWSS_MOD_TEST_NO_ELEVATION -ne "1") { Restart-Elevated }
    $manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot "manifest.json") -Raw | ConvertFrom-Json
    $GamePath = Find-GamePath $GamePath $manifest
    $running = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like "LEGOSTARWARSSKYWALKERSAGA*" }
    if ($running) { throw "The game is running. Close it before uninstalling." }
    $backupDir = Join-Path $GamePath $BackupName
    if (-not (Test-Path -LiteralPath $backupDir)) { throw "Mod backup folder was not found: $backupDir" }
    foreach ($entry in $manifest.files) {
        $destination = Join-Path $GamePath $entry.name
        $backup = Join-Path $backupDir $entry.name
        if (-not (Test-Path -LiteralPath $backup)) { throw "Missing backup: $backup" }
        if ((Get-Sha256 $backup) -ne $entry.sourceSha256) { throw "Backup hash is invalid: $backup" }
        $currentHash = Get-Sha256 $destination
        if ($currentHash -eq $entry.sourceSha256) {
            Write-Host "$($entry.name) is already restored."
            continue
        }
        if ($currentHash -ne $entry.targetSha256) {
            throw "$($entry.name) was changed by another update or mod. Refusing to overwrite it."
        }
        $temp = Join-Path $GamePath ("." + $entry.name + ".restore.tmp")
        Copy-Item -LiteralPath $backup -Destination $temp -Force
        if ((Get-Sha256 $temp) -ne $entry.sourceSha256) { throw "Restore verification failed: $temp" }
        $rollback = $destination + ".restore.rollback.tmp"
        if (Test-Path -LiteralPath $rollback) { Remove-Item -LiteralPath $rollback -Force }
        [IO.File]::Replace($temp, $destination, $rollback, $true)
        if ((Get-Sha256 $destination) -ne $entry.sourceSha256) { throw "Restored hash verification failed: $destination" }
        Remove-Item -LiteralPath $rollback -Force
        Write-Host "Restored $($entry.name)."
    }
    Write-Host "Uninstall completed. The verified official files were restored."
    exit 0
} catch {
    Write-Error $_
    exit 1
}
