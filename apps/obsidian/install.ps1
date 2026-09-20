#Requires -Version 5.1
# ai-leverage/apps/obsidian/install.ps1
# Usage: .\install.ps1 [-Choco]

[CmdletBinding()]
param(
    # Skip winget and install with Chocolatey instead.
    [switch]$Choco
)

# PowerShell's closest equivalent to 'set -e' for cmdlets. Native commands are
# still checked through $LASTEXITCODE below.
$ErrorActionPreference = 'Stop'

# 1. Setup Variables
$RepoDir  = $PSScriptRoot
$LogFile  = Join-Path $RepoDir 'install.log'
$WingetId = 'Obsidian.Obsidian'
$ChocoId  = 'obsidian'

# One fixed encoding for every write to the log. Tee-Object is deliberately avoided:
# in Windows PowerShell it has no -Encoding parameter and writes UTF-16LE, which would
# not match the header and would leave the log unreadable.
$LogEncoding = New-Object System.Text.UTF8Encoding($false)

# 2. Helper: append one line to the log.
# Logging must never be the reason an install fails, so write errors are swallowed.
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
Write-Host "●  Initializing paths:"
Write-Host "   - REPO_DIR: $RepoDir"
Write-Host "   - LOG_FILE: $LogFile"
Write-Host ""
Write-Host "┌── AI-leverage: Installing Obsidian"

# 4. Start a fresh log for this run, falling back to the temp folder if needed
$LogHeader = "=== AI-leverage: Obsidian install - $(Get-Date -Format s) ==="
try {
    [System.IO.File]::WriteAllText($LogFile, $LogHeader + [Environment]::NewLine, $LogEncoding)
}
catch {
    Write-Host "●  Note: '$LogFile' is not writable. Logging to the temp folder instead."
    $LogFile = Join-Path $env:TEMP 'obsidian-install.log'
    [System.IO.File]::WriteAllText($LogFile, $LogHeader + [Environment]::NewLine, $LogEncoding)
}

# 5. Detect the available package managers
$HasWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)
$HasChoco  = [bool](Get-Command choco  -ErrorAction SilentlyContinue)

# 6. Check if already installed
# Any of the three install shapes counts, so re-runs are a no-op.
$InstalledVia = ''

if ($HasWinget) {
    $listed = Invoke-Native -FilePath 'winget' -Quiet -ArgumentList @(
        'list', '--id', $WingetId, '-e', '--accept-source-agreements'
    )
    if ($listed -eq 0) { $InstalledVia = "winget ($WingetId)" }
}

if (-not $InstalledVia) {
    # Version-agnostic Chocolatey check: 'choco list' changed semantics in v2.
    $ChocoRoot = if ($env:ChocolateyInstall) { $env:ChocolateyInstall } else { Join-Path $env:ProgramData 'chocolatey' }
    if (Test-Path -LiteralPath (Join-Path $ChocoRoot "lib\$ChocoId")) {
        $InstalledVia = "Chocolatey ($ChocoId)"
    }
}

if (-not $InstalledVia) {
    # A plain installer run puts Obsidian here without any package manager involved.
    $Candidates = @()
    if ($env:LOCALAPPDATA) { $Candidates += (Join-Path $env:LOCALAPPDATA 'Obsidian\Obsidian.exe') }
    if ($env:ProgramFiles) { $Candidates += (Join-Path $env:ProgramFiles 'Obsidian\Obsidian.exe') }
    $Found = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($Found) { $InstalledVia = $Found }
}

if ($InstalledVia) {
    Write-Host "●  ✓ Obsidian is already installed via $InstalledVia. Skipping installation."
    Write-Host "└── Installation complete."
    exit 0
}

# 7. Pick the installation method
# winget is the primary path; Chocolatey is used on request or when winget is missing.
if (-not $Choco -and -not $HasWinget) {
    Write-Host "●  winget not found. Falling back to Chocolatey (machine-wide, needs admin)."
    $Choco = $true
}

if (-not $Choco) {
    # 8a. Primary: winget
    Write-Host "●  Installing $WingetId with winget:"
    Write-Host "│" # Visual spacer

    $status = Invoke-Native -FilePath 'winget' -ArgumentList @(
        'install', '--id', $WingetId, '-e',
        '--accept-package-agreements', '--accept-source-agreements'
    )

    Write-Host "│" # Visual spacer
    if ($status -ne 0) {
        Write-Host "└── ✗ Installation failed (winget exit code $status). Please check $LogFile for details."
        exit 1
    }
    Write-Host "●  ✓ Obsidian installed successfully via winget."
}
else {
    # 8b. Fallback: Chocolatey
    if (-not $HasChoco) {
        Write-Host "└── ✗ Neither winget nor Chocolatey is available. Install one of them first."
        exit 1
    }

    Write-Host "●  Installing $ChocoId with Chocolatey (admin rights required):"
    Write-Host "│" # Visual spacer

    $status = Invoke-Native -FilePath 'choco' -ArgumentList @('install', $ChocoId, '-y')

    Write-Host "│" # Visual spacer
    if ($status -ne 0) {
        Write-Host "└── ✗ Installation failed (choco exit code $status). Please check $LogFile for details."
        exit 1
    }
    Write-Host "●  ✓ Obsidian installed successfully via Chocolatey."
}

Write-Host "└── Installation complete."
