param(
    [string]$SubjectFilter = ""
)

# ============================================================
# STEP 28 - MOVE SOURCE MESSAGE + COMPLETE WORKFLOW
#
# Prerequisites:
# - current_state = TASK_CREATED
# - durable task exists
# - if draft_required=true, draft_status must be SENT
#
# Transitions:
# TASK_CREATED -> MOVED -> COMPLETED
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

function Add-HistoryEvent {
    param(
        [Parameter(Mandatory)]$Record,
        [AllowNull()]$FromState,
        [Parameter(Mandatory)]$ToState,
        [Parameter(Mandatory)][string]$Note
    )

    $event = [PSCustomObject]@{
        from_state    = if ($null -eq $FromState) { $null } else { [string]$FromState }
        to_state      = [string]$ToState
        occurred_at   = (Get-Date).ToUniversalTime().ToString("o")
        note          = $Note
        error_code    = $null
        error_message = $null
    }

    $history = @()

    if ($null -ne $Record.PSObject.Properties["history"]) {
        $history = @($Record.history)
    }

    Set-RecordProperty `
        -Object $Record `
        -Name "history" `
        -Value @($history + $event)
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
        [string]$_.current_state -eq "TASK_CREATED"
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
    Write-Host "No TASK_CREATED record matched the filter." `
        -ForegroundColor Yellow
    return
}

foreach ($record in $eligibleRecords) {
    if (
        [bool]$record.draft_required -eq $true -and
        [string]$record.draft_status -ne "SENT"
    ) {
        throw (
            "The task requires a reply, but its draft_status is " +
            "'$($record.draft_status)'. Review and send the draft first."
        )
    }
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

$folderUri = (
    "https://graph.microsoft.com/v1.0/users/" +
    $encodedMailbox +
    "/mailFolders" +
    "?includeHiddenFolders=true" +
    "&`$top=100" +
    "&`$select=id,displayName,parentFolderId"
)

$folderResponse = Invoke-RestMethod `
    -Method Get `
    -Uri $folderUri `
    -Headers $headers

foreach ($record in $eligibleRecords) {
    $task = $taskIndex |
        Where-Object {
            [string]$_.task_id -eq [string]$record.task_id
        } |
        Select-Object -First 1

    if ($null -eq $task) {
        throw "Task $($record.task_id) was not found."
    }

    $destinationName = [string]$task.destination_folder_name

    if ([string]::IsNullOrWhiteSpace($destinationName)) {
        throw "Task $($task.task_id) has no destination folder."
    }

    $destinationFolder = $folderResponse.value |
        Where-Object {
            [string]$_.displayName -eq $destinationName
        } |
        Select-Object -First 1

    if ($null -eq $destinationFolder) {
        throw (
            "Destination folder '$destinationName' was not found " +
            "at the shared mailbox root."
        )
    }

    $sourceMessageId = [string]$record.graph_message_id

    if ([string]::IsNullOrWhiteSpace($sourceMessageId)) {
        throw "Source message ID is missing."
    }

    $encodedSourceMessageId = [Uri]::EscapeDataString($sourceMessageId)
    $moveUri = (
        "https://graph.microsoft.com/v1.0/users/" +
        $encodedMailbox +
        "/messages/" +
        $encodedSourceMessageId +
        "/move"
    )

    $moveBody = @{
        destinationId = [string]$destinationFolder.id
    } | ConvertTo-Json

    Write-Host ""
    Write-Host (
        "Moving '$($record.subject)' to $destinationName..."
    ) -ForegroundColor Yellow

    $moveResponse = Invoke-WebRequest `
        -Method Post `
        -Uri $moveUri `
        -Headers $headers `
        -ContentType "application/json" `
        -Body $moveBody `
        -UseBasicParsing

    if ($moveResponse.StatusCode -ne 201) {
        throw "Move returned HTTP $($moveResponse.StatusCode)."
    }

    $movedMessage = $moveResponse.Content | ConvertFrom-Json

    if (
        [string]$movedMessage.parentFolderId -ne
        [string]$destinationFolder.id
    ) {
        throw "Graph returned a moved message with the wrong parent folder."
    }

    $movedAt = (Get-Date).ToUniversalTime().ToString("o")
    $oldState = [string]$record.current_state

    Set-RecordProperty -Object $record -Name "previous_state" -Value $oldState
    Set-RecordProperty -Object $record -Name "current_state" -Value "MOVED"
    Set-RecordProperty -Object $record -Name "graph_message_id" -Value $movedMessage.id
    Set-RecordProperty -Object $record -Name "destination_folder_id" -Value $destinationFolder.id
    Set-RecordProperty -Object $record -Name "destination_folder_name" -Value $destinationName
    Set-RecordProperty -Object $record -Name "moved_at" -Value $movedAt
    Set-RecordProperty -Object $record -Name "updated_at" -Value $movedAt

    Add-HistoryEvent `
        -Record $record `
        -FromState $oldState `
        -ToState "MOVED" `
        -Note "Graph moved the source message to $destinationName."

    # Commit MOVED immediately, before final completion bookkeeping.
    Save-ObjectArrayFile -Path $stateFile -Records @($script:stateRecords)

    Set-RecordProperty -Object $task -Name "graph_message_id" -Value $movedMessage.id
    Set-RecordProperty -Object $task -Name "destination_folder_id" -Value $destinationFolder.id
    Set-RecordProperty -Object $task -Name "status" -Value "COMPLETED"
    Set-RecordProperty -Object $task -Name "moved_at" -Value $movedAt
    Set-RecordProperty -Object $task -Name "completed_at" -Value $movedAt
    Set-RecordProperty -Object $task -Name "updated_at" -Value $movedAt

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

    Set-RecordProperty -Object $record -Name "previous_state" -Value "MOVED"
    Set-RecordProperty -Object $record -Name "current_state" -Value "COMPLETED"
    Set-RecordProperty -Object $record -Name "completed_at" -Value $movedAt
    Set-RecordProperty -Object $record -Name "updated_at" -Value $movedAt

    Add-HistoryEvent `
        -Record $record `
        -FromState "MOVED" `
        -ToState "COMPLETED" `
        -Note (
            "Task $($task.task_id), draft/send status, destination folder, " +
            "and moved Graph message ID were committed."
        )

    Save-ObjectArrayFile -Path $stateFile -Records @($script:stateRecords)

    Write-Host "Workflow completed successfully." -ForegroundColor Green

    [PSCustomObject]@{
        TaskId                = $task.task_id
        FinalState            = $record.current_state
        DestinationFolder     = $destinationName
        DestinationFolderId   = $destinationFolder.id
        CurrentGraphMessageId = $movedMessage.id
        DraftStatus           = $record.draft_status
        CompletedAt           = $record.completed_at
    } | Format-List
}

Write-Host ""
Write-Host "Step 28 finished." -ForegroundColor Green
