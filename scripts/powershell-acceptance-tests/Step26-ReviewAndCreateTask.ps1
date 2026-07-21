param(
    [string]$SubjectFilter = "",
    [string]$Reviewer = "",
    [ValidateSet("", "APPROVED", "CORRECTED", "REJECTED")]
    [string]$Decision = ""
)

# ============================================================
# STEP 26 - HUMAN REVIEW + DURABLE TASK CREATION
#
# Normal transition:
# CLASSIFIED -> TASK_CREATED
#
# This script does NOT call Microsoft Graph, create drafts,
# send mail, or move messages.
# ============================================================

$ErrorActionPreference = "Stop"

$baseDirectory = Join-Path $env:USERPROFILE "Desktop\Astra-Licensing-Graph"
$processingDirectory = Join-Path $baseDirectory "processing"
$stateFile = Join-Path $processingDirectory "state\email_processing_state.json"
$reviewRoot = Join-Path $processingDirectory "reviews"
$taskRoot = Join-Path $processingDirectory "tasks"
$taskIndexFile = Join-Path $taskRoot "tasks_index.json"

foreach ($directory in @($reviewRoot, $taskRoot)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}

if (-not (Test-Path $stateFile)) {
    throw "Processing state file was not found: $stateFile"
}

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

    if (
        $names -contains "record_key" -and
        $names -contains "current_state"
    ) {
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

    if (-not (Test-Path $Path)) {
        return @()
    }

    $raw = Get-Content -LiteralPath $Path -Raw

    if ([string]::IsNullOrWhiteSpace($raw)) {
        return @()
    }

    $root = $raw | ConvertFrom-Json

    if ($ProcessingRecords) {
        return @(Find-ProcessingRecord -Node $root)
    }

    if ($root -is [System.Array]) {
        return @($root)
    }

    return @($root)
}

function Save-ObjectArrayFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][object[]]$Records
    )

    $parts = @(
        $Records |
        ForEach-Object {
            $_ | ConvertTo-Json -Depth 50
        }
    )

    $payload = if ($parts.Count -eq 0) {
        "[]"
    }
    else {
        "[`r`n" + ($parts -join ",`r`n") + "`r`n]"
    }

    $temporaryPath = "$Path.tmp"

    Set-Content `
        -LiteralPath $temporaryPath `
        -Value $payload `
        -Encoding UTF8

    # Validate before replacing the live file.
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
        from_state  = if ($null -eq $FromState) { $null } else { [string]$FromState }
        to_state    = [string]$ToState
        occurred_at = (Get-Date).ToUniversalTime().ToString("o")
        note        = $Note
        error_code  = $null
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

function Read-OptionalValue {
    param(
        [Parameter(Mandatory)][string]$Prompt,
        [AllowNull()]$CurrentValue
    )

    $display = if ($null -eq $CurrentValue) {
        ""
    }
    elseif ($CurrentValue -is [System.Array]) {
        $CurrentValue -join ", "
    }
    else {
        [string]$CurrentValue
    }

    $value = Read-Host "$Prompt [$display]"

    if ([string]::IsNullOrWhiteSpace($value)) {
        return $CurrentValue
    }

    return $value.Trim()
}

function Get-DestinationFolderName {
    param($Classification)

    if ([string]$Classification.vendor -eq "NMLS") {
        return "04_NMLS"
    }

    switch ([string]$Classification.email_type) {
        "missing_information_request" { return "08_Info_Required" }
        "bond_correspondence"         { return "03_Cornerstone_Bonds" }
        "invoice_or_fee"              { return "06_Invoices" }
        "submission_confirmation"     { return "07_Proof_Received" }
        "license_or_proof_received"   { return "07_Proof_Received" }
        "regulator_correspondence"    { return "05_Regulators" }
        "renewal_notice" {
            if ([string]$Classification.vendor -eq "RASI") {
                return "02_RASI"
            }
            return "05_Regulators"
        }
        default { return "09_Internal_Followups" }
    }
}

function Get-DraftRequired {
    param($Classification)

    return (
        [string]$Classification.email_type -in @(
            "missing_information_request",
            "regulator_correspondence"
        )
    )
}

function New-SafeDraftBody {
    param($Classification)

    $lines = @(
        "Hello,",
        "",
        "Thank you for your message regarding the licensing matter below.",
        ""
    )

    if (@($Classification.states).Count -gt 0) {
        $lines += "Jurisdiction: $(@($Classification.states) -join ', ')"
    }

    if (@($Classification.license_types).Count -gt 0) {
        $lines += "License type: $(@($Classification.license_types) -join ', ')"
    }

    if (@($Classification.requested_information).Count -gt 0) {
        $lines += ""
        $lines += "We are reviewing the following requested information:"

        foreach ($item in @($Classification.requested_information)) {
            $lines += "- $item"
        }
    }

    $lines += ""
    $lines += (
        "We will follow up after the information has been verified " +
        "and approved internally."
    )
    $lines += ""
    $lines += "Regards,"
    $lines += "Astra Licensing"

    return ($lines -join "`r`n")
}

$script:stateRecords = @(
    Read-ObjectArrayFile `
        -Path $stateFile `
        -ProcessingRecords
)

if ($script:stateRecords.Count -eq 0) {
    throw "No processing records were found in $stateFile"
}

$eligibleRecords = @(
    $script:stateRecords |
    Where-Object {
        [string]$_.current_state -eq "CLASSIFIED"
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
    Write-Host "No CLASSIFIED record matched the filter." -ForegroundColor Yellow
    return
}

if ([string]::IsNullOrWhiteSpace($Reviewer)) {
    $Reviewer = Read-Host "Reviewer name or work email"
}

if ([string]::IsNullOrWhiteSpace($Reviewer)) {
    throw "Reviewer is required."
}

$taskIndex = @(
    Read-ObjectArrayFile -Path $taskIndexFile
)

foreach ($record in $eligibleRecords) {
    if (
        [string]::IsNullOrWhiteSpace(
            [string]$record.classification_path
        ) -or
        -not (Test-Path $record.classification_path)
    ) {
        throw "Classification file is missing for: $($record.subject)"
    }

    $classification = Get-Content `
        -LiteralPath $record.classification_path `
        -Raw |
        ConvertFrom-Json

    Write-Host ""
    Write-Host "Classification for review" -ForegroundColor Cyan

    [PSCustomObject]@{
        Subject              = $record.subject
        Vendor               = $classification.vendor
        EmailType            = $classification.email_type
        States               = @($classification.states) -join ", "
        LicenseTypes         = @($classification.license_types) -join ", "
        LicenseNumbers       = @($classification.license_numbers) -join ", "
        ActionRequired       = $classification.action_required
        DueDate              = $classification.due_date
        Confidence           = $classification.confidence
        RequestedInformation = @($classification.requested_information) -join "; "
        ProposedAction       = $classification.proposed_action
    } | Format-List

    $currentDecision = $Decision

    if ([string]::IsNullOrWhiteSpace($currentDecision)) {
        $currentDecision = Read-Host `
            "Decision: APPROVED, CORRECTED, or REJECTED"
    }

    $currentDecision = $currentDecision.Trim().ToUpperInvariant()

    if ($currentDecision -notin @("APPROVED", "CORRECTED", "REJECTED")) {
        throw "Decision must be APPROVED, CORRECTED, or REJECTED."
    }

    # Deep clone so the original classifier evidence is never overwritten.
    $reviewedClassification = (
        $classification |
        ConvertTo-Json -Depth 50 |
        ConvertFrom-Json
    )

    $reviewNotes = ""

    if ($currentDecision -eq "CORRECTED") {
        $vendor = Read-OptionalValue `
            -Prompt "Vendor" `
            -CurrentValue $reviewedClassification.vendor

        Set-RecordProperty `
            -Object $reviewedClassification `
            -Name "vendor" `
            -Value ([string]$vendor)

        $emailType = Read-OptionalValue `
            -Prompt "Email type" `
            -CurrentValue $reviewedClassification.email_type

        Set-RecordProperty `
            -Object $reviewedClassification `
            -Name "email_type" `
            -Value ([string]$emailType)

        $statesText = Read-OptionalValue `
            -Prompt "States, comma-separated" `
            -CurrentValue @($reviewedClassification.states)

        $states = if ($statesText -is [System.Array]) {
            @($statesText)
        }
        else {
            @(
                ([string]$statesText) -split "," |
                ForEach-Object { $_.Trim() } |
                Where-Object { $_ }
            )
        }

        Set-RecordProperty `
            -Object $reviewedClassification `
            -Name "states" `
            -Value $states

        $licenseTypesText = Read-OptionalValue `
            -Prompt "License types, comma-separated" `
            -CurrentValue @($reviewedClassification.license_types)

        $licenseTypes = if ($licenseTypesText -is [System.Array]) {
            @($licenseTypesText)
        }
        else {
            @(
                ([string]$licenseTypesText) -split "," |
                ForEach-Object { $_.Trim() } |
                Where-Object { $_ }
            )
        }

        Set-RecordProperty `
            -Object $reviewedClassification `
            -Name "license_types" `
            -Value $licenseTypes

        $dueDate = Read-OptionalValue `
            -Prompt "Due date YYYY-MM-DD, or leave unchanged" `
            -CurrentValue $reviewedClassification.due_date

        if (
            -not [string]::IsNullOrWhiteSpace([string]$dueDate) -and
            [string]$dueDate -notmatch "^\d{4}-\d{2}-\d{2}$"
        ) {
            throw "Corrected due date must use YYYY-MM-DD."
        }

        Set-RecordProperty `
            -Object $reviewedClassification `
            -Name "due_date" `
            -Value $dueDate

        $requestedText = Read-OptionalValue `
            -Prompt "Requested information, separated by semicolons" `
            -CurrentValue @($reviewedClassification.requested_information)

        $requestedItems = if ($requestedText -is [System.Array]) {
            @($requestedText)
        }
        else {
            @(
                ([string]$requestedText) -split ";" |
                ForEach-Object { $_.Trim() } |
                Where-Object { $_ }
            )
        }

        Set-RecordProperty `
            -Object $reviewedClassification `
            -Name "requested_information" `
            -Value $requestedItems

        $proposedAction = Read-OptionalValue `
            -Prompt "Proposed action" `
            -CurrentValue $reviewedClassification.proposed_action

        Set-RecordProperty `
            -Object $reviewedClassification `
            -Name "proposed_action" `
            -Value ([string]$proposedAction)

        $reviewNotes = Read-Host "Correction notes"
    }
    else {
        $reviewNotes = Read-Host "Review notes (optional)"
    }

    $reviewedAt = (Get-Date).ToUniversalTime().ToString("o")
    $recordReviewDirectory = Join-Path $reviewRoot $record.record_key

    New-Item `
        -ItemType Directory `
        -Path $recordReviewDirectory `
        -Force |
        Out-Null

    $reviewPath = Join-Path $recordReviewDirectory "review.json"

    $review = [PSCustomObject]@{
        review_schema_version = "1.0"
        record_key            = $record.record_key
        mailbox_address       = $record.mailbox_address
        graph_message_id      = $record.graph_message_id
        internet_message_id   = $record.internet_message_id
        conversation_id       = $record.conversation_id
        subject               = $record.subject
        decision              = $currentDecision
        reviewer              = $Reviewer
        reviewed_at           = $reviewedAt
        review_notes          = $reviewNotes
        source_classification_path = $record.classification_path
        reviewed_classification = $reviewedClassification
    }

    $review |
        ConvertTo-Json -Depth 50 |
        Set-Content `
            -LiteralPath $reviewPath `
            -Encoding UTF8

    Set-RecordProperty `
        -Object $record `
        -Name "review_path" `
        -Value $reviewPath

    Set-RecordProperty `
        -Object $record `
        -Name "review_status" `
        -Value $currentDecision

    Set-RecordProperty `
        -Object $record `
        -Name "reviewer" `
        -Value $Reviewer

    Set-RecordProperty `
        -Object $record `
        -Name "reviewed_at" `
        -Value $reviewedAt

    if ($currentDecision -eq "REJECTED") {
        Add-HistoryEvent `
            -Record $record `
            -FromState "CLASSIFIED" `
            -ToState "CLASSIFIED" `
            -Note "Human reviewer rejected the classification; no task was created."

        Save-ObjectArrayFile `
            -Path $stateFile `
            -Records @($script:stateRecords)

        Write-Host "Review saved as REJECTED. No task created." `
            -ForegroundColor Yellow

        continue
    }

    $taskId = "LIC-$($record.record_key)"
    $taskPath = Join-Path $taskRoot "$taskId.json"
    $destinationFolderName = Get-DestinationFolderName `
        -Classification $reviewedClassification
    $draftRequired = Get-DraftRequired `
        -Classification $reviewedClassification

    $taskTitleParts = @()

    if (@($reviewedClassification.states).Count -gt 0) {
        $taskTitleParts += (@($reviewedClassification.states) -join ", ")
    }

    if (@($reviewedClassification.license_types).Count -gt 0) {
        $taskTitleParts += (@($reviewedClassification.license_types) -join ", ")
    }

    if ([string]$reviewedClassification.email_type) {
        $taskTitleParts += (
            ([string]$reviewedClassification.email_type) -replace "_", " "
        )
    }

    $taskTitle = if ($taskTitleParts.Count -gt 0) {
        $taskTitleParts -join " - "
    }
    else {
        [string]$record.subject
    }

    $task = [PSCustomObject]@{
        task_schema_version      = "1.0"
        task_id                  = $taskId
        record_key               = $record.record_key
        mailbox_address          = $record.mailbox_address
        graph_message_id         = $record.graph_message_id
        internet_message_id      = $record.internet_message_id
        conversation_id          = $record.conversation_id
        source_subject           = $record.subject
        title                    = $taskTitle
        status                   = "OPEN"
        queue                    = $destinationFolderName
        destination_folder_name  = $destinationFolderName
        vendor                   = $reviewedClassification.vendor
        email_type               = $reviewedClassification.email_type
        states                   = @($reviewedClassification.states)
        license_types            = @($reviewedClassification.license_types)
        license_numbers          = @($reviewedClassification.license_numbers)
        requested_information    = @($reviewedClassification.requested_information)
        documents                = @($reviewedClassification.documents)
        due_date                 = $reviewedClassification.due_date
        summary                  = $reviewedClassification.summary
        proposed_action          = $reviewedClassification.proposed_action
        review_status            = $currentDecision
        reviewer                 = $Reviewer
        review_path              = $reviewPath
        classification_path      = $record.classification_path
        draft_required           = [bool]$draftRequired
        draft_body               = if ($draftRequired) {
            New-SafeDraftBody -Classification $reviewedClassification
        }
        else {
            $null
        }
        draft_status             = if ($draftRequired) { "PENDING" } else { "NOT_REQUIRED" }
        draft_message_id         = $null
        draft_web_link           = $null
        created_at               = $reviewedAt
        updated_at               = $reviewedAt
        completed_at             = $null
    }

    $task |
        ConvertTo-Json -Depth 50 |
        Set-Content `
            -LiteralPath $taskPath `
            -Encoding UTF8

    $taskIndex = @(
        $taskIndex |
        Where-Object {
            [string]$_.task_id -ne $taskId
        }
    ) + $task

    Save-ObjectArrayFile `
        -Path $taskIndexFile `
        -Records @($taskIndex)

    $oldState = [string]$record.current_state

    Set-RecordProperty `
        -Object $record `
        -Name "previous_state" `
        -Value $oldState

    Set-RecordProperty `
        -Object $record `
        -Name "current_state" `
        -Value "TASK_CREATED"

    Set-RecordProperty `
        -Object $record `
        -Name "task_id" `
        -Value $taskId

    Set-RecordProperty `
        -Object $record `
        -Name "task_path" `
        -Value $taskPath

    Set-RecordProperty `
        -Object $record `
        -Name "destination_folder_name" `
        -Value $destinationFolderName

    Set-RecordProperty `
        -Object $record `
        -Name "draft_required" `
        -Value ([bool]$draftRequired)

    Set-RecordProperty `
        -Object $record `
        -Name "draft_status" `
        -Value $task.draft_status

    Set-RecordProperty `
        -Object $record `
        -Name "updated_at" `
        -Value $reviewedAt

    Add-HistoryEvent `
        -Record $record `
        -FromState $oldState `
        -ToState "TASK_CREATED" `
        -Note (
            "Human review completed with decision $currentDecision. " +
            "Durable licensing task $taskId was created."
        )

    Save-ObjectArrayFile `
        -Path $stateFile `
        -Records @($script:stateRecords)

    Write-Host ""
    Write-Host "TASK_CREATED" -ForegroundColor Green

    [PSCustomObject]@{
        TaskId            = $taskId
        Title             = $task.title
        Queue             = $destinationFolderName
        DueDate           = $task.due_date
        DraftRequired     = $draftRequired
        ReviewDecision    = $currentDecision
        ReviewPath        = $reviewPath
        TaskPath          = $taskPath
    } | Format-List
}

Write-Host ""
Write-Host "Step 26 finished. No email was drafted, sent, or moved." `
    -ForegroundColor Green
