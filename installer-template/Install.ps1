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

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
}

function Find-GamePath([string]$Requested, $Manifest) {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($Requested) { $candidates.Add($Requested) | Out-Null }
    $steamRoots = @()
    foreach ($registryPath in @(
        "HKCU:\Software\Valve\Steam",
        "HKLM:\SOFTWARE\WOW6432Node\Valve\Steam",
        "HKLM:\SOFTWARE\Valve\Steam"
    )) {
        try {
            $item = Get-ItemProperty -Path $registryPath
            if ($item.SteamPath) { $steamRoots += $item.SteamPath }
            if ($item.InstallPath) { $steamRoots += $item.InstallPath }
        } catch {}
    }
    $steamRoots += @("C:\Program Files (x86)\Steam", "C:\Program Files\Steam")
    foreach ($root in ($steamRoots | Select-Object -Unique)) {
        if (-not $root) { continue }
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
        if (Test-Path -LiteralPath (Join-Path $candidate $Manifest.gameExecutable)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw "Game installation was not found. Run: Install.cmd <full game path>"
}

function New-VerifiedBackup([string]$Source, [string]$Backup, [string]$ExpectedHash) {
    if (Test-Path -LiteralPath $Backup) {
        if ((Get-Sha256 $Backup) -ne $ExpectedHash) {
            throw "Existing backup has an unexpected hash: $Backup"
        }
        return
    }
    try {
        New-Item -ItemType HardLink -Path $Backup -Target $Source | Out-Null
    } catch {
        Copy-Item -LiteralPath $Source -Destination $Backup
    }
    if ((Get-Sha256 $Backup) -ne $ExpectedHash) {
        throw "Backup verification failed: $Backup"
    }
}

function Build-PatchedFile([string]$Source, [string]$PatchPath, [string]$TempPath, [UInt64]$ExpectedSize, [string]$ExpectedHash) {
    Copy-Item -LiteralPath $Source -Destination $TempPath -Force
    $patchStream = [IO.File]::OpenRead($PatchPath)
    try {
        $gzip = New-Object IO.Compression.GZipStream($patchStream, [IO.Compression.CompressionMode]::Decompress)
        try {
            $reader = New-Object IO.BinaryReader($gzip)
            $magic = [Text.Encoding]::ASCII.GetString($reader.ReadBytes(8))
            if ($magic -ne "LSWSPAT1") { throw "Invalid patch format: $PatchPath" }
            $size = $reader.ReadUInt64()
            if ($size -ne $ExpectedSize) { throw "Patch size metadata mismatch: $PatchPath" }
            $output = [IO.File]::Open($TempPath, [IO.FileMode]::Open, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try {
                while ($true) {
                    $offset = $reader.ReadUInt64()
                    $length = $reader.ReadUInt32()
                    if ($offset -eq [UInt64]::MaxValue -and $length -eq 0) { break }
                    $data = $reader.ReadBytes([int]$length)
                    if ($data.Length -ne $length) { throw "Patch ended early: $PatchPath" }
                    $output.Position = [Int64]$offset
                    $output.Write($data, 0, $data.Length)
                }
                $output.Flush($true)
            } finally { $output.Dispose() }
        } finally { $gzip.Dispose() }
    } finally { $patchStream.Dispose() }
    if ((Get-Item -LiteralPath $TempPath).Length -ne $ExpectedSize) {
        throw "Patched file size verification failed: $TempPath"
    }
    if ((Get-Sha256 $TempPath) -ne $ExpectedHash) {
        throw "Patched file hash verification failed: $TempPath"
    }
}

try {
    if (-not (Test-Administrator) -and $env:LSWSS_MOD_TEST_NO_ELEVATION -ne "1") { Restart-Elevated }
    $manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot "manifest.json") -Raw | ConvertFrom-Json
    $GamePath = Find-GamePath $GamePath $manifest
    Write-Host "Game: $GamePath"
    $running = Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -like "LEGOSTARWARSSKYWALKERSAGA*"
    }
    if ($running) { throw "The game is running. Close it before installing." }

    $backupDir = Join-Path $GamePath $BackupName
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    $jobs = @()
    foreach ($entry in $manifest.files) {
        $destination = Join-Path $GamePath $entry.name
        $patchPath = Join-Path $PSScriptRoot $entry.patch
        if (-not (Test-Path -LiteralPath $destination)) { throw "Missing game file: $destination" }
        if ((Get-Sha256 $patchPath) -ne $entry.patchSha256) { throw "Patch package is damaged: $patchPath" }
        $currentHash = Get-Sha256 $destination
        if ($currentHash -eq $entry.targetSha256) {
            $backup = Join-Path $backupDir $entry.name
            if (-not (Test-Path -LiteralPath $backup)) {
                $legacyBackup = $destination + ".codex-bitmap-probe.original"
                if ((Test-Path -LiteralPath $legacyBackup) -and ((Get-Sha256 $legacyBackup) -eq $entry.sourceSha256)) {
                    New-VerifiedBackup $legacyBackup $backup $entry.sourceSha256
                    Write-Host "Imported the verified existing backup for $($entry.name)."
                } else {
                    Write-Warning "$($entry.name) is already installed, but no verified official backup is available to the package uninstaller. Steam Verify Integrity can still restore it."
                }
            }
            Write-Host "$($entry.name) is already installed."
            continue
        }
        if ($currentHash -ne $entry.sourceSha256) {
            throw "$($entry.name) is not the supported official version. Use Steam Verify Integrity, then run the installer again."
        }
        $backup = Join-Path $backupDir $entry.name
        New-VerifiedBackup $destination $backup $entry.sourceSha256
        $temp = Join-Path $GamePath ("." + $entry.name + ".scmod.tmp")
        $reuseTemp = $false
        if (Test-Path -LiteralPath $temp) {
            $reuseTemp = ((Get-Item -LiteralPath $temp).Length -eq [UInt64]$entry.size) -and ((Get-Sha256 $temp) -eq $entry.targetSha256)
            if (-not $reuseTemp) { Remove-Item -LiteralPath $temp -Force }
        }
        if ($reuseTemp) {
            Write-Host "Reusing verified temporary $($entry.name)."
        } else {
            Write-Host "Building $($entry.name)..."
            Build-PatchedFile $backup $patchPath $temp ([UInt64]$entry.size) $entry.targetSha256
        }
        $jobs += [pscustomobject]@{ Entry = $entry; Destination = $destination; Temp = $temp }
    }

    foreach ($job in $jobs) {
        $rollback = $job.Destination + ".scmod.rollback.tmp"
        if (Test-Path -LiteralPath $rollback) { Remove-Item -LiteralPath $rollback -Force }
        [IO.File]::Replace($job.Temp, $job.Destination, $rollback, $true)
        if ((Get-Sha256 $job.Destination) -ne $job.Entry.targetSha256) {
            throw "Installed hash verification failed: $($job.Destination)"
        }
        Remove-Item -LiteralPath $rollback -Force
        Write-Host "Installed $($job.Entry.name)."
    }
    Write-Host "Installation completed successfully. Traditional Chinese now loads the Mainland Simplified Chinese mod."
    exit 0
} catch {
    Write-Error $_
    exit 1
}
