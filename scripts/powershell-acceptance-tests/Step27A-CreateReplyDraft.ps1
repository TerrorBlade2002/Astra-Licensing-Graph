param(
    [string]$SubjectFilter = ""
)

# ============================================================
# STEP 27A - CREATE AN OUTLOOK REPLY DRAFT
#
# Reads TASK_CREATED records whose task says draft_required=true.
# Creates a reply draft in the shared mailbox, updates its body,
# and records the returned draft ID and Outlook web link.
#
# This script DOES NOT send the draft or move the source email.
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
        [bool]$_.draft_required -eq $true -and
        [string]$_.draft_status -notin @("CREATED", "SENT")
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
    Write-Host "No TASK_CREATED record currently requires a draft." `
        -ForegroundColor Yellow
    return
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
    $task = $taskIndex |
        Where-Object {
            [string]$_.task_id -eq [string]$record.task_id
        } |
        Select-Object -First 1

    if ($null -eq $task) {
        throw "Task $($record.task_id) was not found in tasks_index.json."
    }

    if ([string]::IsNullOrWhiteSpace([string]$task.draft_body)) {
        throw "Task $($task.task_id) has no draft_body."
    }

    $sourceMessageId = [string]$record.graph_message_id

    if ([string]::IsNullOrWhiteSpace($sourceMessageId)) {
        throw "The source Graph message ID is missing."
    }

    $encodedSourceMessageId = [Uri]::EscapeDataString($sourceMessageId)
    $createReplyUri = (
        "https://graph.microsoft.com/v1.0/users/" +
        $encodedMailbox +
        "/messages/" +
        $encodedSourceMessageId +
        "/createReply"
    )

    Write-Host ""
    Write-Host "Creating reply draft for: $($record.subject)" `
        -ForegroundColor Yellow

    $createResponse = Invoke-WebRequest `
        -Method Post `
        -Uri $createReplyUri `
        -Headers $headers `
        -UseBasicParsing

    if ($createResponse.StatusCode -notin @(200, 201)) {
        throw "createReply returned HTTP $($createResponse.StatusCode)."
    }

    $draft = $createResponse.Content | ConvertFrom-Json
    $draftId = [string]$draft.id

    if ([string]::IsNullOrWhiteSpace($draftId)) {
        throw "Graph created no usable draft ID."
    }

    $encodedDraftId = [Uri]::EscapeDataString($draftId)
    $draftUri = (
        "https://graph.microsoft.com/v1.0/users/" +
        $encodedMailbox +
        "/messages/" +
        $encodedDraftId
    )

    $patchBody = @{
        body = @{
            contentType = "text"
            content     = [string]$task.draft_body
        }
        importance = "normal"
    } | ConvertTo-Json -Depth 10

    $patchResponse = Invoke-WebRequest `
        -Method Patch `
        -Uri $draftUri `
        -Headers $headers `
        -ContentType "application/json" `
        -Body $patchBody `
        -UseBasicParsing

    if ($patchResponse.StatusCode -ne 200) {
        throw "Draft update returned HTTP $($patchResponse.StatusCode)."
    }

    $updatedDraft = $patchResponse.Content | ConvertFrom-Json
    $createdAt = (Get-Date).ToUniversalTime().ToString("o")

    Set-RecordProperty -Object $record -Name "draft_status" -Value "CREATED"
    Set-RecordProperty -Object $record -Name "draft_message_id" -Value $updatedDraft.id
    Set-RecordProperty -Object $record -Name "draft_web_link" -Value $updatedDraft.webLink
    Set-RecordProperty -Object $record -Name "draft_created_at" -Value $createdAt
    Set-RecordProperty -Object $record -Name "updated_at" -Value $createdAt

    Set-RecordProperty -Object $task -Name "draft_status" -Value "CREATED"
    Set-RecordProperty -Object $task -Name "draft_message_id" -Value $updatedDraft.id
    Set-RecordProperty -Object $task -Name "draft_web_link" -Value $updatedDraft.webLink
    Set-RecordProperty -Object $task -Name "draft_created_at" -Value $createdAt
    Set-RecordProperty -Object $task -Name "updated_at" -Value $createdAt

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

    Write-Host "Reply draft created successfully." -ForegroundColor Green

    [PSCustomObject]@{
        TaskId       = $task.task_id
        DraftId      = $updatedDraft.id
        Subject      = $updatedDraft.subject
        IsDraft      = $updatedDraft.isDraft
        ToRecipients = @(
            $updatedDraft.toRecipients |
            ForEach-Object { $_.emailAddress.address }
        ) -join "; "
        WebLink      = $updatedDraft.webLink
    } | Format-List
}

Write-Host ""
Write-Host (
    "Step 27A finished. Review the draft in the shared mailbox Drafts folder. " +
    "Nothing was sent or moved."
) -ForegroundColor Green
