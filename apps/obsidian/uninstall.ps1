#Requires -Version 5.1
# ai-leverage/apps/obsidian/uninstall.ps1
# Usage: .\uninstall.ps1

[CmdletBinding()]
param()

# PowerShell's closest equivalent to 'set -e' for cmdlets. Native commands are
# still checked through $LASTEXITCODE below.
$ErrorActionPreference = 'Stop'

# 1. Setup Variables
$RepoDir    = $PSScriptRoot
$LogFile    = Join-Path $RepoDir 'uninstall.log'
$WingetId   = 'Obsidian.Obsidian'
$ChocoId    = 'obsidian'
$AppDataDir = Join-Path $env:APPDATA 'obsidian'

# One fixed encoding for every write to the log. Tee-Object is deliberately avoided:
# in Windows PowerShell it has no -Encoding parameter and writes UTF-16LE, which would
# not match the header and would leave the log unreadable.
$LogEncoding = New-Object System.Text.UTF8Encoding($false)

# 2. Helper: append one line to the log.
# Logging must never be the reason an uninstall fails, so write errors are swallowed.
function Write-Log {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Message)
    try {
        [System.IO.File]::AppendAllText($script:LogFile, $Message + [Environment]::NewLine, $script:LogEncoding)
    }
    catch {
        # Deliberately ignored - see above.
    }
}

# 3. Helper: run a native command, mirroring its output to the console and the log.
function Invoke-Native {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [switch]$Quiet
    )

    $previous = $ErrorActionPreference
    # Windows PowerShell turns merged stderr into a terminating error while
    # $ErrorActionPreference is 'Stop', so it is relaxed for the duration of the call.
    $ErrorActionPreference = 'Continue'

    # A command that never launches leaves the previous $LASTEXITCODE in place, and a
    # stale 0 would then read as success. Clear it and treat "never ran" as a failure.
    $global:LASTEXITCODE = $null

    try {
        if ($Quiet) {
            & $FilePath @ArgumentList *> $null
        }
        else {
            & $FilePath @ArgumentList 2>&1 | ForEach-Object {
                $line = ($_ | Out-String).TrimEnd()
                Write-Host $line
                Write-Log $line
            }
        }
    }
    catch {
        Write-Host "●  Could not run '$FilePath': $($_.Exception.Message)"
        return 9999
    }
    finally {
        $ErrorActionPreference = $previous
    }

    if ($null -eq $LASTEXITCODE) { return 9999 }
    return $LASTEXITCODE
}

Clear-Host
Write-Host "┌── AI-leverage: Uninstalling Obsidian"

# 4. Start a fresh log for this run, falling back to the temp folder if needed
$LogHeader = "=== AI-leverage: Obsidian uninstall - $(Get-Date -Format s) ==="
try {
    [System.IO.File]::WriteAllText($LogFile, $LogHeader + [Environment]::NewLine, $LogEncoding)
}
catch {
    Write-Host "●  Note: '$LogFile' is not writable. Logging to the temp folder instead."
    $LogFile = Join-Path $env:TEMP 'obsidian-uninstall.log'
    [System.IO.File]::WriteAllText($LogFile, $LogHeader + [Environment]::NewLine, $LogEncoding)
}

# 5. Detect the available package managers
$HasWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)
$HasChoco  = [bool](Get-Command choco  -ErrorAction SilentlyContinue)

$Removed = $false

# 6. Remove the winget package
if ($HasWinget) {
    $listed = Invoke-Native -FilePath 'winget' -Quiet -ArgumentList @(
        'list', '--id', $WingetId, '-e', '--accept-source-agreements'
    )

    if ($listed -eq 0) {
        Write-Host "●  Removing $WingetId with winget..."
        Write-Host "│" # Visual spacer

        $status = Invoke-Native -FilePath 'winget' -ArgumentList @(
            'uninstall', '--id', $WingetId, '-e', '--accept-source-agreements'
        )

        Write-Host "│" # Visual spacer
        if ($status -ne 0) {
            Write-Host "└── ✗ Failed to remove the winget package (exit code $status). Please check $LogFile for details."
            exit 1
        }
        Write-Host "●  ✓ winget package removed."
        $Removed = $true
    }
}

# 7. Remove the Chocolatey package
# Version-agnostic check: 'choco list' changed semantics in v2.
$ChocoRoot = if ($env:ChocolateyInstall) { $env:ChocolateyInstall } else { Join-Path $env:ProgramData 'chocolatey' }
if ($HasChoco -and (Test-Path -LiteralPath (Join-Path $ChocoRoot "lib\$ChocoId"))) {
    Write-Host "●  Removing $ChocoId with Chocolatey (admin rights required):"
    Write-Host "│" # Visual spacer

    $status = Invoke-Native -FilePath 'choco' -ArgumentList @('uninstall', $ChocoId, '-y')

    Write-Host "│" # Visual spacer
    if ($status -ne 0) {
        Write-Host "└── ✗ Failed to remove the Chocolatey package (exit code $status). Please check $LogFile for details."
        exit 1
    }
    Write-Host "●  ✓ Chocolatey package removed."
    $Removed = $true
}

# 8. Nothing found means nothing to do, so re-runs stay safe
if (-not $Removed) {
    # install.ps1 also treats a plain installer run as installed, so do not claim the
    # app is absent when the executable is sitting right there.
    $Candidates = @()
    if ($env:LOCALAPPDATA) { $Candidates += (Join-Path $env:LOCALAPPDATA 'Obsidian\Obsidian.exe') }
    if ($env:ProgramFiles) { $Candidates += (Join-Path $env:ProgramFiles 'Obsidian\Obsidian.exe') }
    $OtherExe = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

    if ($OtherExe) {
        Write-Host "●  Obsidian is installed outside winget and Chocolatey, at: $OtherExe"
        Write-Host "●  That is a plain installer run, which this script does not manage."
        Write-Host "└── Aborted. Remove it through Settings > Apps > Installed apps."
    }
    else {
        Write-Host "●  Obsidian is not installed (no winget package, no Chocolatey package)."
        Write-Host "└── Aborted. Nothing to uninstall."
    }

    Write-Host "●  Note: Your vaults and their per-vault settings in <vault>\.obsidian are untouched."
    Write-Host "●  Uninstallers typically preserve user data."
    Write-Host "●  If you want to remove ALL Obsidian app data, run:"
    Write-Host "●    Remove-Item -Recurse -Force `"$AppDataDir`""
    exit 0
}

# 9. Inform user about what was done and what's preserved
Write-Host "└── ✓ Obsidian application removed."
Write-Host "●  Note: Your vaults and their per-vault settings in <vault>\.obsidian are untouched."
Write-Host "●  Uninstallers typically preserve user data."
Write-Host "●  If you want to remove ALL Obsidian app data, run:"
Write-Host "●    Remove-Item -Recurse -Force `"$AppDataDir`""
