param(
    [string]$SubjectFilter = "",
    [Parameter(Mandatory)]
    [ValidateSet("SEND")]
    [string]$ConfirmSend
)

# ============================================================
# STEP 27B - SEND AN EXPLICITLY APPROVED OUTLOOK DRAFT
#
# Safety: requires -ConfirmSend SEND.
# Sends an existing shared-mailbox reply draft.
#
# This script DOES NOT move the original source message.
# ============================================================

$ErrorActionPreference = "Stop"

$tenantId = "58b1714c-43be-4fb1-acbe-ea1ac4d8a850"
$clientId = "996d8468-d4db-4963-967d-951a61832e9a"
$mailbox  = "astralicensing@astraglobal.com"

$baseDirectory = Join-Path $env:USERPROFILE "Desktop\Astra-Licensing-Graph"
$processingDirectory = Join-Path $baseDirectory "processing"
$stateFile = Join-Path $processingDirectory "state\email_processing_state.json"
$taskIndexFile = Join-Path $processingDirectory "tasks\tasks_index.json"

function Find-ProcessingRecord {
    param([AllowNull()][object]$Node)

    if ($null -eq $Node) { return }

    if ($Node -is [System.Array]) {
        foreach ($item in $Node) {
            Find-ProcessingRecord -Node $item
        }
        return
    }

    if ($Node -isnot [System.Management.Automation.PSCustomObject]) {
        return
    }

    $names = @($Node.PSObject.Properties | ForEach-Object { $_.Name })

    if ($names -contains "record_key" -and $names -contains "current_state") {
        Write-Output $Node
        return
    }

    foreach ($property in $Node.PSObject.Properties) {
        Find-ProcessingRecord -Node $property.Value
    }
}

function Read-ObjectArrayFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [switch]$ProcessingRecords
    )

    if (-not (Test-Path $Path)) { return @() }

    $raw = Get-Content -LiteralPath $Path -Raw

    if ([string]::IsNullOrWhiteSpace($raw)) { return @() }

    $root = $raw | ConvertFrom-Json

    if ($ProcessingRecords) {
        return @(Find-ProcessingRecord -Node $root)
    }

    if ($root -is [System.Array]) { return @($root) }

    return @($root)
}

function Save-ObjectArrayFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][object[]]$Records
    )

    $parts = @(
        $Records |
        ForEach-Object { $_ | ConvertTo-Json -Depth 50 }
    )

    $payload = if ($parts.Count -eq 0) {
        "[]"
    }
    else {
        "[`r`n" + ($parts -join ",`r`n") + "`r`n]"
    }

    $temporaryPath = "$Path.tmp"

    Set-Content -LiteralPath $temporaryPath -Value $payload -Encoding UTF8
    $null = Get-Content -LiteralPath $temporaryPath -Raw | ConvertFrom-Json

    Move-Item `
        -LiteralPath $temporaryPath `
        -Destination $Path `
        -Force
}

function Set-RecordProperty {
    param(
        [Parameter(Mandatory)]$Object,
        [Parameter(Mandatory)][string]$Name,
        $Value
    )

    $Object |
        Add-Member `
            -MemberType NoteProperty `
            -Name $Name `
            -Value $Value `
            -Force
}

function Get-FreshGraphToken {
    $secureSecret = Read-Host `
        "Paste the current Entra client secret VALUE" `
        -AsSecureString

    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR(
        $secureSecret
    )

    try {
        $clientSecret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
            $pointer
        )

        $body = @{
            client_id     = $clientId
            client_secret = $clientSecret
            scope         = "https://graph.microsoft.com/.default"
            grant_type    = "client_credentials"
        }

        $response = Invoke-RestMethod `
            -Method Post `
            -Uri "https://login.microsoftonline.com/$tenantId/oauth2/v2.0/token" `
            -ContentType "application/x-www-form-urlencoded" `
            -Body $body

        return $response.access_token
    }
    finally {
        if ($pointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        }

        $clientSecret = $null
        $secureSecret = $null
    }
}

$script:stateRecords = @(
    Read-ObjectArrayFile -Path $stateFile -ProcessingRecords
)

$taskIndex = @(
    Read-ObjectArrayFile -Path $taskIndexFile
)

$eligibleRecords = @(
    $script:stateRecords |
    Where-Object {
        [string]$_.current_state -eq "TASK_CREATED" -and
        [string]$_.draft_status -eq "CREATED"
    }
)

if (-not [string]::IsNullOrWhiteSpace($SubjectFilter)) {
    $eligibleRecords = @(
        $eligibleRecords |
        Where-Object {
            [string]$_.subject -like "*$SubjectFilter*"
        }
    )
}

if ($eligibleRecords.Count -eq 0) {
    Write-Host "No CREATED draft matched the filter." -ForegroundColor Yellow
    return
}

Write-Host ""
Write-Host "The following drafts will be sent:" -ForegroundColor Yellow

$eligibleRecords |
    Select-Object subject,task_id,draft_message_id |
    Format-Table -Wrap -AutoSize

$interactiveConfirmation = Read-Host `
    "Type SEND again to confirm the live send"

if ($interactiveConfirmation.Trim().ToUpperInvariant() -ne "SEND") {
    throw "Send cancelled."
}

$accessToken = Get-FreshGraphToken

if ([string]::IsNullOrWhiteSpace($accessToken)) {
    throw "No Graph access token was returned."
}

$headers = @{
    Authorization = "Bearer $accessToken"
    Accept        = "application/json"
    Prefer        = 'IdType="ImmutableId"'
}

$encodedMailbox = [Uri]::EscapeDataString($mailbox)

foreach ($record in $eligibleRecords) {
    $draftId = [string]$record.draft_message_id

    if ([string]::IsNullOrWhiteSpace($draftId)) {
        throw "Draft ID is missing for: $($record.subject)"
    }

    $task = $taskIndex |
        Where-Object {
            [string]$_.task_id -eq [string]$record.task_id
        } |
        Select-Object -First 1

    if ($null -eq $task) {
        throw "Task $($record.task_id) was not found."
    }

    $encodedDraftId = [Uri]::EscapeDataString($draftId)
    $sendUri = (
        "https://graph.microsoft.com/v1.0/users/" +
        $encodedMailbox +
        "/messages/" +
        $encodedDraftId +
        "/send"
    )

    Write-Host "Sending draft for: $($record.subject)" `
        -ForegroundColor Yellow

    $sendResponse = Invoke-WebRequest `
        -Method Post `
        -Uri $sendUri `
        -Headers $headers `
        -UseBasicParsing

    if ($sendResponse.StatusCode -ne 202) {
        throw "Draft send returned HTTP $($sendResponse.StatusCode)."
    }

    $sentAt = (Get-Date).ToUniversalTime().ToString("o")

    Set-RecordProperty -Object $record -Name "draft_status" -Value "SENT"
    Set-RecordProperty -Object $record -Name "draft_sent_at" -Value $sentAt
    Set-RecordProperty -Object $record -Name "updated_at" -Value $sentAt

    Set-RecordProperty -Object $task -Name "draft_status" -Value "SENT"
    Set-RecordProperty -Object $task -Name "draft_sent_at" -Value $sentAt
    Set-RecordProperty -Object $task -Name "updated_at" -Value $sentAt

    if (
        -not [string]::IsNullOrWhiteSpace([string]$record.task_path) -and
        (Test-Path $record.task_path)
    ) {
        $task |
            ConvertTo-Json -Depth 50 |
            Set-Content `
                -LiteralPath $record.task_path `
                -Encoding UTF8
    }

    Save-ObjectArrayFile -Path $taskIndexFile -Records @($taskIndex)
    Save-ObjectArrayFile -Path $stateFile -Records @($script:stateRecords)

    Write-Host "Graph accepted the draft for sending: HTTP 202." `
        -ForegroundColor Green
}

Write-Host ""
Write-Host (
    "Step 27B finished. Check the shared mailbox Sent Items folder " +
    "before running Step 28."
) -ForegroundColor Green
