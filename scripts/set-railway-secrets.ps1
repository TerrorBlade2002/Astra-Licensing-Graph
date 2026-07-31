# Prompt for the deployment secrets and set them as Railway variables.
#
# The values are typed into this window and passed straight to the Railway CLI.
# They are never written to a file, a log, or the shell history, and this script
# prints only variable names when it verifies the result.
#
# Nothing is deployed: every set uses --skip-deploys, so services keep running
# their current configuration until you choose to redeploy.

[CmdletBinding()]
param(
    # Check which variables exist without prompting for anything.
    [switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'

# Work from the repository root; the Railway project link is stored per
# directory, so running from anywhere else gives "No linked project found".
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# Locate the CLI without depending on the calling shell's PATH, which is stale
# in any window opened before the CLI was installed. An elevated session also
# resolves $env:APPDATA to a different profile, so several roots are tried.
function Resolve-RailwayCli {
    $candidates = @()
    foreach ($root in $env:APPDATA, "$env:USERPROFILE\AppData\Roaming", "$HOME\AppData\Roaming") {
        if ($root) { $candidates += (Join-Path $root 'npm\railway.cmd') }
    }
    try {
        $prefix = (& npm config get prefix 2>$null | Select-Object -First 1)
        if ($prefix) { $candidates += (Join-Path $prefix.Trim() 'railway.cmd') }
    } catch { }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
    $onPath = Get-Command railway -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }

    Write-Host 'Could not find the Railway CLI. Checked:' -ForegroundColor Red
    $candidates | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    Write-Host ''
    Write-Host 'Install it with:  npm install -g @railway/cli' -ForegroundColor Yellow
    Write-Host 'Or set the variables in the Railway dashboard instead.' -ForegroundColor Yellow
    exit 1
}

$railway = Resolve-RailwayCli
Write-Host "Using Railway CLI: $railway" -ForegroundColor DarkGray

function Get-SecretText([string]$Label) {
    $secure = Read-Host -Prompt $Label -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

function Show-Status {
    Write-Host ''
    Write-Host 'Current state (names only):' -ForegroundColor Cyan
    foreach ($service in 'backend', 'worker', 'scheduler') {
        $json = & $railway variables --service $service --json 2>$null
        if (-not $json) {
            Write-Host ("  {0,-10} could not read variables" -f $service) -ForegroundColor Yellow
            continue
        }
        $names = ($json | ConvertFrom-Json).PSObject.Properties.Name
        $present = @()
        foreach ($key in 'GRAPH_CLIENT_SECRET', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY') {
            if ($names -contains $key) { $present += $key }
        }
        $summary = if ($present.Count) { $present -join ', ' } else { 'none set' }
        Write-Host ("  {0,-10} {1}" -f $service, $summary)
    }
}

& $railway status | Select-Object -First 6
if ($VerifyOnly) { Show-Status; return }

Write-Host ''
Write-Host 'Paste each value, then press Enter. Typing is hidden.' -ForegroundColor Cyan
Write-Host 'Press Enter on its own to skip a value.' -ForegroundColor DarkGray
Write-Host ''

$graphSecret = Get-SecretText 'Graph client secret'
$r2KeyId     = Get-SecretText 'R2 access key ID'
$r2Secret    = Get-SecretText 'R2 secret access key'

if ($graphSecret) {
    # The worker and scheduler authenticate to Graph independently of the API.
    foreach ($service in 'backend', 'worker', 'scheduler') {
        & $railway variables --service $service --skip-deploys --set "GRAPH_CLIENT_SECRET=$graphSecret" | Out-Null
        Write-Host "  GRAPH_CLIENT_SECRET set on $service" -ForegroundColor Green
    }
}

if ($r2KeyId -and $r2Secret) {
    # Only the services that write document evidence need R2 credentials.
    foreach ($service in 'backend', 'worker') {
        & $railway variables --service $service --skip-deploys `
            --set "R2_ACCESS_KEY_ID=$r2KeyId" --set "R2_SECRET_ACCESS_KEY=$r2Secret" | Out-Null
        Write-Host "  R2 credentials set on $service" -ForegroundColor Green
    }
} elseif ($r2KeyId -or $r2Secret) {
    Write-Host '  R2 needs both the key ID and the secret; neither was set.' -ForegroundColor Yellow
}

$graphSecret = $null; $r2KeyId = $null; $r2Secret = $null
[GC]::Collect()

Show-Status

Write-Host ''
Write-Host 'Done. Nothing was deployed.' -ForegroundColor Cyan
Write-Host 'Rotate these credentials once the deployment is confirmed working.' -ForegroundColor DarkGray
