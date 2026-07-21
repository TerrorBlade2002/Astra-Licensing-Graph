param(
    [string]$ChangesFile
)

# ============================================================
# STEP 24 — DURABLE EMAIL PROCESSING STATES
# Processes Step 23 UPSERT records through:
# DISCOVERED -> FETCHED -> ATTACHMENTS_SAVED
# ============================================================

$ErrorActionPreference = "Stop"

# ------------------------------------------------------------
# 1. CONFIGURATION
# ------------------------------------------------------------

$tenantId = "58b1714c-43be-4fb1-acbe-ea1ac4d8a850"
$clientId = "996d8468-d4db-4963-967d-951a61832e9a"
$mailbox  = "astralicensing@astraglobal.com"

$baseDirectory = Join-Path `
    $env:USERPROFILE `
    "Desktop\Astra-Licensing-Graph"

$deltaOutputDirectory = Join-Path `
    $baseDirectory `
    "delta-output"

$processingDirectory = Join-Path `
    $baseDirectory `
    "processing"

$stateDirectory = Join-Path `
    $processingDirectory `
    "state"

$rawDirectory = Join-Path `
    $processingDirectory `
    "raw-emails"

$attachmentDirectory = Join-Path `
    $processingDirectory `
    "attachments"

$stateFile = Join-Path `
    $stateDirectory `
    "email_processing_state.json"

foreach ($directory in @(
    $processingDirectory,
    $stateDirectory,
    $rawDirectory,
    $attachmentDirectory
)) {
    New-Item `
        -ItemType Directory `
        -Path $directory `
        -Force |
        Out-Null
}

# ------------------------------------------------------------
# 2. CHOOSE STEP 23 CHANGES FILE
# ------------------------------------------------------------

if ([string]::IsNullOrWhiteSpace($ChangesFile)) {
    $latestChangesFile = Get-ChildItem `
        -Path $deltaOutputDirectory `
        -Filter "inbox_changes_*.json" `
        -File |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1

    if ($null -eq $latestChangesFile) {
        throw (
            "No Step 23 delta output was found in: " +
            $deltaOutputDirectory
        )
    }

    $ChangesFile = $latestChangesFile.FullName
}

if (-not (Test-Path $ChangesFile)) {
    throw "Changes file does not exist: $ChangesFile"
}

Write-Host "Using delta file:" -ForegroundColor Cyan
Write-Host $ChangesFile

$deltaChanges = @(
    Get-Content `
        -Path $ChangesFile `
        -Raw |
        ConvertFrom-Json
)

# ------------------------------------------------------------
# 3. STATE DEFINITIONS
# ------------------------------------------------------------

$allowedTransitions = @{
    "DISCOVERED" = @(
        "FETCHED",
        "FAILED_RETRYABLE",
        "FAILED_REVIEW"
    )

    "FETCHED" = @(
        "ATTACHMENTS_SAVED",
        "FAILED_RETRYABLE",
        "FAILED_REVIEW"
    )

    "ATTACHMENTS_SAVED" = @(
        "CLASSIFIED",
        "FAILED_RETRYABLE",
        "FAILED_REVIEW"
    )

    "CLASSIFIED" = @(
        "TASK_CREATED",
        "FAILED_RETRYABLE",
        "FAILED_REVIEW"
    )

    "TASK_CREATED" = @(
        "MOVED",
        "FAILED_RETRYABLE",
        "FAILED_REVIEW"
    )

    "MOVED" = @(
        "COMPLETED",
        "FAILED_RETRYABLE",
        "FAILED_REVIEW"
    )

    "FAILED_RETRYABLE" = @(
        "DISCOVERED",
        "FAILED_REVIEW"
    )

    # A reviewed record may be manually reset later.
    "FAILED_REVIEW" = @(
        "DISCOVERED"
    )

    "COMPLETED" = @()
}

# ------------------------------------------------------------
# 4. LOAD EXISTING STATE STORE
# ------------------------------------------------------------

$script:processingRecords = @()

if (Test-Path $stateFile) {
    $existingContent = Get-Content `
        -Path $stateFile `
        -Raw

    if (-not [string]::IsNullOrWhiteSpace($existingContent)) {
        $script:processingRecords = @(
            $existingContent |
            ConvertFrom-Json
        )
    }
}

# ------------------------------------------------------------
# 5. HELPER FUNCTIONS
# ------------------------------------------------------------

function Save-ProcessingState {
    $temporaryPath = "$stateFile.tmp"

    ConvertTo-Json `
        -InputObject @($script:processingRecords) `
        -Depth 20 |
        Set-Content `
            -Path $temporaryPath `
            -Encoding UTF8

    Move-Item `
        -Path $temporaryPath `
        -Destination $stateFile `
        -Force
}

function Get-TextSha256 {
    param(
        [Parameter(Mandatory)]
        [string]$Text
    )

    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)

    $sha256 = [Security.Cryptography.SHA256]::Create()

    try {
        $hashBytes = $sha256.ComputeHash($bytes)

        return (
            [BitConverter]::ToString($hashBytes)
        ).Replace("-", "")
    }
    finally {
        $sha256.Dispose()
    }
}

function Get-SafeFilename {
    param(
        [Parameter(Mandatory)]
        [string]$Name
    )

    $filename = [IO.Path]::GetFileName($Name)

    if ([string]::IsNullOrWhiteSpace($filename)) {
        $filename = "unnamed-file.bin"
    }

    $invalidCharacters = [IO.Path]::GetInvalidFileNameChars()

    return -join (
        $filename.ToCharArray() |
        ForEach-Object {
            if ($invalidCharacters -contains $_) {
                "_"
            }
            else {
                $_
            }
        }
    )
}

function Set-ProcessingState {
    param(
        [Parameter(Mandatory)]
        $Record,

        [Parameter(Mandatory)]
        [string]$NewState,

        [string]$Note,

        [string]$ErrorCode,

        [string]$ErrorMessage
    )

    $oldState = $Record.current_state

    if ($oldState -eq $NewState) {
        return
    }

    if (
        -not (
            $allowedTransitions[$oldState] -contains $NewState
        )
    ) {
        throw (
            "Invalid processing-state transition: " +
            "$oldState -> $NewState"
        )
    }

    $timestamp = (
        Get-Date
    ).ToUniversalTime().ToString("o")

    $historyEvent = [PSCustomObject]@{
        from_state    = $oldState
        to_state      = $NewState
        occurred_at   = $timestamp
        note          = $Note
        error_code    = $ErrorCode
        error_message = $ErrorMessage
    }

    $Record.previous_state = $oldState
    $Record.current_state = $NewState
    $Record.updated_at = $timestamp

    $Record.last_error_code = $ErrorCode
    $Record.last_error_message = $ErrorMessage

    $Record.history = @(
        $Record.history
    ) + $historyEvent

    Save-ProcessingState

    Write-Host (
        "$($Record.subject): $oldState -> $NewState"
    ) -ForegroundColor Green
}

function Get-HttpStatusCode {
    param(
        [Parameter(Mandatory)]
        $ErrorRecord
    )

    try {
        if ($null -ne $ErrorRecord.Exception.Response.StatusCode) {
            return [int]$ErrorRecord.Exception.Response.StatusCode
        }
    }
    catch {
    }

    return $null
}

# ------------------------------------------------------------
# 6. GET A FRESH GRAPH TOKEN
# ------------------------------------------------------------

Write-Host ""
Write-Host "Requesting fresh Graph token..." `
    -ForegroundColor Cyan

$secureSecret = Read-Host `
    "Paste the current Entra client secret VALUE" `
    -AsSecureString

$secretPointer =
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR(
        $secureSecret
    )

try {
    $clientSecret =
        [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
            $secretPointer
        )

    $tokenBody = @{
        client_id     = $clientId
        client_secret = $clientSecret
        scope         = "https://graph.microsoft.com/.default"
        grant_type    = "client_credentials"
    }

    $tokenResponse = Invoke-RestMethod `
        -Method Post `
        -Uri (
            "https://login.microsoftonline.com/" +
            $tenantId +
            "/oauth2/v2.0/token"
        ) `
        -ContentType "application/x-www-form-urlencoded" `
        -Body $tokenBody
}
finally {
    if ($secretPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR(
            $secretPointer
        )
    }

    $clientSecret = $null
    $secureSecret = $null
}

$accessToken = $tokenResponse.access_token

if ([string]::IsNullOrWhiteSpace($accessToken)) {
    throw "No Graph access token was returned."
}

$graphHeaders = @{
    Authorization = "Bearer $accessToken"
    Accept        = "application/json"
    Prefer        = (
        'outlook.body-content-type="text", ' +
        'IdType="ImmutableId"'
    )
}

$binaryHeaders = @{
    Authorization = "Bearer $accessToken"
    Accept        = "*/*"
    Prefer        = 'IdType="ImmutableId"'
}

$encodedMailbox = [Uri]::EscapeDataString($mailbox)

# ------------------------------------------------------------
# 7. PROCESS DELTA CHANGES
# ------------------------------------------------------------

foreach ($change in $deltaChanges) {

    # A removal means it is no longer in Inbox.
    # Do not process it as a new message.
    if ($change.change_action -eq "REMOVED_FROM_INBOX") {
        $existingRemovedRecord =
            $script:processingRecords |
            Where-Object {
                $_.graph_message_id -eq
                $change.graph_message_id
            } |
            Select-Object -First 1

        if ($null -ne $existingRemovedRecord) {
            $existingRemovedRecord.inbox_membership = "REMOVED"
            $existingRemovedRecord.updated_at = (
                Get-Date
            ).ToUniversalTime().ToString("o")

            Save-ProcessingState
        }

        continue
    }

    if ($change.change_action -ne "UPSERT") {
        continue
    }

    $dedupeValue = if (
        -not [string]::IsNullOrWhiteSpace(
            $change.internet_message_id
        )
    ) {
        $change.internet_message_id
    }
    else {
        $change.graph_message_id
    }

    $recordKey = (
        Get-TextSha256 `
            -Text "$mailbox|$dedupeValue"
    ).Substring(0, 24)

    $record =
        $script:processingRecords |
        Where-Object {
            $_.record_key -eq $recordKey
        } |
        Select-Object -First 1

    # --------------------------------------------------------
    # CREATE DISCOVERED RECORD ONCE
    # --------------------------------------------------------

    if ($null -eq $record) {
        $now = (
            Get-Date
        ).ToUniversalTime().ToString("o")

        $record = [PSCustomObject]@{
            record_key              = $recordKey
            mailbox_address         = $mailbox
            graph_message_id        = $change.graph_message_id
            internet_message_id     = $change.internet_message_id
            conversation_id         = $change.conversation_id
            subject                 = $change.subject
            sender_email            = $change.sender_email
            received_at             = $change.received_at

            current_state           = "DISCOVERED"
            previous_state          = $null
            inbox_membership        = "PRESENT"

            raw_json_path           = $null
            raw_mime_path           = $null
            attachment_manifest_path = $null
            attachment_count        = $null

            classification_path     = $null
            task_id                 = $null
            destination_folder_id   = $null

            retry_count             = 0
            next_retry_at           = $null
            last_error_code         = $null
            last_error_message      = $null

            source_delta_file       = $ChangesFile
            discovered_at           = $now
            updated_at              = $now
            completed_at            = $null

            history = @(
                [PSCustomObject]@{
                    from_state    = $null
                    to_state      = "DISCOVERED"
                    occurred_at   = $now
                    note          = "Message reported by Inbox delta query."
                    error_code    = $null
                    error_message = $null
                }
            )
        }

        $script:processingRecords = @(
            $script:processingRecords
        ) + $record

        Save-ProcessingState

        Write-Host ""
        Write-Host (
            "DISCOVERED: " +
            $record.subject
        ) -ForegroundColor Cyan
    }
    else {
        # Update mutable Graph values from the latest delta event.
        $record.graph_message_id =
            $change.graph_message_id

        $record.subject =
            $change.subject

        $record.sender_email =
            $change.sender_email

        $record.updated_at = (
            Get-Date
        ).ToUniversalTime().ToString("o")

        Save-ProcessingState
    }

    # Completed or already prepared messages are not repeated.
    if ($record.current_state -in @(
        "ATTACHMENTS_SAVED",
        "CLASSIFIED",
        "TASK_CREATED",
        "MOVED",
        "COMPLETED"
    )) {
        Write-Host (
            "Skipping already processed message at state " +
            "$($record.current_state): $($record.subject)"
        ) -ForegroundColor DarkGray

        continue
    }

    # Retry automatically from the beginning of safe ingestion.
    if ($record.current_state -eq "FAILED_RETRYABLE") {
        if (
            -not [string]::IsNullOrWhiteSpace(
                $record.next_retry_at
            ) -and
            [datetime]$record.next_retry_at -gt
            (Get-Date).ToUniversalTime()
        ) {
            Write-Host (
                "Retry not due yet: $($record.subject)"
            ) -ForegroundColor Yellow

            continue
        }

        Set-ProcessingState `
            -Record $record `
            -NewState "DISCOVERED" `
            -Note "Retrying safe ingestion from discovery."
    }

    try {
        # ----------------------------------------------------
        # DISCOVERED -> FETCHED
        # ----------------------------------------------------

        if ($record.current_state -eq "DISCOVERED") {
            $messageId = $record.graph_message_id

            if ([string]::IsNullOrWhiteSpace($messageId)) {
                throw "Message has no Graph message ID."
            }

            $encodedMessageId =
                [Uri]::EscapeDataString($messageId)

            $messageDirectory = Join-Path `
                $rawDirectory `
                $record.record_key

            New-Item `
                -ItemType Directory `
                -Path $messageDirectory `
                -Force |
                Out-Null

            $messageJsonPath = Join-Path `
                $messageDirectory `
                "message.json"

            $messageMimePath = Join-Path `
                $messageDirectory `
                "message.eml"

            $messageUri = (
                "https://graph.microsoft.com/v1.0/users/" +
                $encodedMailbox +
                "/messages/" +
                $encodedMessageId +
                "?`$select=id,subject,from,toRecipients," +
                "ccRecipients,bccRecipients,receivedDateTime," +
                "sentDateTime,body,bodyPreview,hasAttachments," +
                "conversationId,internetMessageId,isRead," +
                "parentFolderId,lastModifiedDateTime"
            )

            $fullMessage = Invoke-RestMethod `
                -Method Get `
                -Uri $messageUri `
                -Headers $graphHeaders

            $fullMessage |
                ConvertTo-Json -Depth 15 |
                Set-Content `
                    -Path $messageJsonPath `
                    -Encoding UTF8

            $mimeUri = (
                "https://graph.microsoft.com/v1.0/users/" +
                $encodedMailbox +
                "/messages/" +
                $encodedMessageId +
                "/`$value"
            )

            Invoke-WebRequest `
                -Method Get `
                -Uri $mimeUri `
                -Headers $binaryHeaders `
                -OutFile $messageMimePath `
                -UseBasicParsing

            if (
                -not (Test-Path $messageJsonPath) -or
                -not (Test-Path $messageMimePath)
            ) {
                throw "Raw message evidence was not saved."
            }

            if (
                (Get-Item $messageMimePath).Length -eq 0
            ) {
                throw "Saved MIME message is empty."
            }

            $record.graph_message_id =
                $fullMessage.id

            $record.internet_message_id =
                $fullMessage.internetMessageId

            $record.conversation_id =
                $fullMessage.conversationId

            $record.raw_json_path =
                $messageJsonPath

            $record.raw_mime_path =
                $messageMimePath

            Set-ProcessingState `
                -Record $record `
                -NewState "FETCHED" `
                -Note (
                    "Structured Graph message and raw MIME " +
                    "were saved."
                )
        }

        # ----------------------------------------------------
        # FETCHED -> ATTACHMENTS_SAVED
        # ----------------------------------------------------

        if ($record.current_state -eq "FETCHED") {
            $encodedMessageId =
                [Uri]::EscapeDataString(
                    $record.graph_message_id
                )

            $messageAttachmentDirectory = Join-Path `
                $attachmentDirectory `
                $record.record_key

            New-Item `
                -ItemType Directory `
                -Path $messageAttachmentDirectory `
                -Force |
                Out-Null

            $manifestPath = Join-Path `
                $messageAttachmentDirectory `
                "attachment_manifest.json"

            $attachmentBaseUri = (
                "https://graph.microsoft.com/v1.0/users/" +
                $encodedMailbox +
                "/messages/" +
                $encodedMessageId +
                "/attachments"
            )

            $attachmentListUri = (
                $attachmentBaseUri +
                "?`$top=100" +
                "&`$select=id,name,contentType,size," +
                "isInline,lastModifiedDateTime"
            )

            $attachments = @()
            $nextUri = $attachmentListUri

            while (
                -not [string]::IsNullOrWhiteSpace(
                    $nextUri
                )
            ) {
                $response = Invoke-RestMethod `
                    -Method Get `
                    -Uri $nextUri `
                    -Headers $graphHeaders

                $attachments += @($response.value)
                $nextUri = $response.'@odata.nextLink'
            }

            $manifest = @()
            $attachmentNumber = 0

            foreach ($attachment in $attachments) {
                $attachmentNumber++

                $attachmentType =
                    $attachment.'@odata.type'

                $safeName = Get-SafeFilename `
                    -Name $attachment.name

                $storedName = (
                    "{0:D2}_{1}" -f
                    $attachmentNumber,
                    $safeName
                )

                $storagePath = Join-Path `
                    $messageAttachmentDirectory `
                    $storedName

                if (
                    $attachmentType -eq
                    "#microsoft.graph.referenceAttachment"
                ) {
                    $manifest += [PSCustomObject]@{
                        attachment_id     = $attachment.id
                        attachment_type   = $attachmentType
                        original_filename = $attachment.name
                        stored_filename   = $null
                        mime_type         = $attachment.contentType
                        graph_size_bytes  = $attachment.size
                        local_size_bytes  = $null
                        is_inline         = $attachment.isInline
                        storage_path      = $null
                        sha256_checksum   = $null
                        status            = "REFERENCE_NOT_DOWNLOADED"
                        downloaded_at     = $null
                    }

                    continue
                }

                $encodedAttachmentId =
                    [Uri]::EscapeDataString(
                        $attachment.id
                    )

                $downloadUri = (
                    $attachmentBaseUri +
                    "/" +
                    $encodedAttachmentId +
                    "/`$value"
                )

                Invoke-WebRequest `
                    -Method Get `
                    -Uri $downloadUri `
                    -Headers $binaryHeaders `
                    -OutFile $storagePath `
                    -UseBasicParsing

                $fileInfo = Get-Item $storagePath

                if ($fileInfo.Length -eq 0) {
                    throw (
                        "Downloaded attachment is empty: " +
                        $attachment.name
                    )
                }

                $fileHash = Get-FileHash `
                    -Path $storagePath `
                    -Algorithm SHA256

                $manifest += [PSCustomObject]@{
                    attachment_id     = $attachment.id
                    attachment_type   = $attachmentType
                    original_filename = $attachment.name
                    stored_filename   = $storedName
                    mime_type         = $attachment.contentType
                    graph_size_bytes  = $attachment.size
                    local_size_bytes  = $fileInfo.Length
                    is_inline         = $attachment.isInline
                    storage_path      = $fileInfo.FullName
                    sha256_checksum   = $fileHash.Hash
                    status            = "DOWNLOADED"
                    downloaded_at     = (
                        Get-Date
                    ).ToUniversalTime().ToString("o")
                }
            }

            ConvertTo-Json `
                -InputObject @($manifest) `
                -Depth 10 |
                Set-Content `
                    -Path $manifestPath `
                    -Encoding UTF8

            if (-not (Test-Path $manifestPath)) {
                throw "Attachment manifest was not saved."
            }

            $record.attachment_manifest_path =
                $manifestPath

            $record.attachment_count =
                @($attachments).Count

            Set-ProcessingState `
                -Record $record `
                -NewState "ATTACHMENTS_SAVED" `
                -Note (
                    "Attachment inspection completed. " +
                    "$(@($attachments).Count) attachment(s) found."
                )
        }
    }
    catch {
        $statusCode = Get-HttpStatusCode `
            -ErrorRecord $_

        $errorMessage = $_.Exception.Message

        $retryableStatusCodes = @(
            408,
            429,
            500,
            502,
            503,
            504
        )

        $record.retry_count =
            [int]$record.retry_count + 1

        if ($retryableStatusCodes -contains $statusCode) {
            $retryAfterSeconds = $null

            try {
                $retryAfterSeconds =
                    [int]$_.Exception.Response.Headers[
                        "Retry-After"
                    ]
            }
            catch {
            }

            if (
                $null -eq $retryAfterSeconds -or
                $retryAfterSeconds -le 0
            ) {
                $retryAfterSeconds = [Math]::Min(
                    [Math]::Pow(
                        2,
                        [int]$record.retry_count
                    ) * 60,
                    3600
                )
            }

            $record.next_retry_at = (
                (Get-Date).ToUniversalTime().AddSeconds(
                    $retryAfterSeconds
                )
            ).ToString("o")

            Set-ProcessingState `
                -Record $record `
                -NewState "FAILED_RETRYABLE" `
                -Note (
                    "Temporary Graph/storage failure. " +
                    "Retry scheduled."
                ) `
                -ErrorCode "$statusCode" `
                -ErrorMessage $errorMessage
        }
        else {
            $record.next_retry_at = $null

            Set-ProcessingState `
                -Record $record `
                -NewState "FAILED_REVIEW" `
                -Note (
                    "Non-retryable failure requires review."
                ) `
                -ErrorCode "$statusCode" `
                -ErrorMessage $errorMessage
        }
    }
}

# ------------------------------------------------------------
# 8. DISPLAY CURRENT STATE
# ------------------------------------------------------------

Write-Host ""
Write-Host "Current processing records:" `
    -ForegroundColor Cyan

$script:processingRecords |
    Sort-Object received_at |
    Select-Object `
        subject,
        sender_email,
        current_state,
        attachment_count,
        retry_count,
        last_error_code,
        next_retry_at |
    Format-Table `
        -Wrap `
        -AutoSize

Write-Host ""
Write-Host "State store:" -ForegroundColor Green
Write-Host $stateFile

Write-Host ""
Write-Host (
    "Step 24 stops at ATTACHMENTS_SAVED. " +
    "No messages were moved."
) -ForegroundColor Green