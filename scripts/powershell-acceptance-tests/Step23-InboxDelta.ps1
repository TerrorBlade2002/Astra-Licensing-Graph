# ============================================================
# STEP 23 — INCREMENTAL INBOX INGESTION USING DELTA QUERY
# ============================================================

$ErrorActionPreference = "Stop"

# ------------------------------------------------------------
# 1. CONFIGURATION
# ------------------------------------------------------------

$tenantId = "58b1714c-43be-4fb1-acbe-ea1ac4d8a850"
$clientId = "996d8468-d4db-4963-967d-951a61832e9a"
$mailbox  = "astralicensing@astraglobal.com"

$stateDirectory = Join-Path `
    $env:USERPROFILE `
    "Desktop\Astra-Licensing-Graph\delta-state"

$outputDirectory = Join-Path `
    $env:USERPROFILE `
    "Desktop\Astra-Licensing-Graph\delta-output"

$statePath = Join-Path `
    $stateDirectory `
    "inbox_sync_state.json"

New-Item `
    -ItemType Directory `
    -Path $stateDirectory `
    -Force |
    Out-Null

New-Item `
    -ItemType Directory `
    -Path $outputDirectory `
    -Force |
    Out-Null

$runTimestamp = Get-Date -Format "yyyyMMdd_HHmmss"

$changesJsonPath = Join-Path `
    $outputDirectory `
    "inbox_changes_$runTimestamp.json"

$changesCsvPath = Join-Path `
    $outputDirectory `
    "inbox_changes_$runTimestamp.csv"

# ------------------------------------------------------------
# 2. HELPER: READ AN HTTP ERROR RESPONSE
# ------------------------------------------------------------

function Get-HttpErrorDetails {
    param(
        [Parameter(Mandatory)]
        $ErrorRecord
    )

    $details = $ErrorRecord.Exception.Message

    try {
        if ($null -ne $ErrorRecord.Exception.Response) {
            $responseStream =
                $ErrorRecord.Exception.Response.GetResponseStream()

            if ($null -ne $responseStream) {
                $reader =
                    New-Object System.IO.StreamReader(
                        $responseStream
                    )

                $responseBody = $reader.ReadToEnd()
                $reader.Close()

                if (
                    -not [string]::IsNullOrWhiteSpace(
                        $responseBody
                    )
                ) {
                    $details += "`n$responseBody"
                }
            }
        }
    }
    catch {
        # Keep the original exception text if response reading fails.
    }

    return $details
}

# ------------------------------------------------------------
# 3. GET A FRESH APP-ONLY ACCESS TOKEN
# ------------------------------------------------------------

Write-Host "Requesting a fresh Graph access token..." `
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
    throw "Microsoft Entra did not return an access token."
}

Write-Host "Fresh access token acquired." `
    -ForegroundColor Green

Write-Host (
    "Token expires in " +
    $tokenResponse.expires_in +
    " seconds."
)

# ------------------------------------------------------------
# 4. BUILD GRAPH HEADERS
# ------------------------------------------------------------

$headers = @{
    Authorization = "Bearer $accessToken"
    Accept        = "application/json"

    # Return up to 50 items per delta page and consistently
    # request immutable message identifiers.
    Prefer = 'odata.maxpagesize=50, IdType="ImmutableId"'
}

$encodedMailbox = [Uri]::EscapeDataString($mailbox)

# ------------------------------------------------------------
# 5. RESOLVE THE ACTUAL INBOX FOLDER ID
# ------------------------------------------------------------

$inboxUri = (
    "https://graph.microsoft.com/v1.0/users/" +
    $encodedMailbox +
    "/mailFolders/inbox" +
    "?%24select=id,displayName,totalItemCount," +
    "unreadItemCount"
)

$inboxFolder = Invoke-RestMethod `
    -Method Get `
    -Uri $inboxUri `
    -Headers $headers

$inboxFolderId = $inboxFolder.id

if ([string]::IsNullOrWhiteSpace($inboxFolderId)) {
    throw "Graph returned no Inbox folder ID."
}

Write-Host ""
Write-Host "Inbox resolved:" -ForegroundColor Green
Write-Host "Folder ID:        $inboxFolderId"
Write-Host "Current messages: $($inboxFolder.totalItemCount)"
Write-Host "Unread messages:  $($inboxFolder.unreadItemCount)"

# ------------------------------------------------------------
# 6. LOAD OR INITIALIZE SYNC STATE
# ------------------------------------------------------------

$state = [PSCustomObject]@{
    mailbox_address  = $mailbox
    folder_id        = $inboxFolderId
    folder_name      = "Inbox"
    delta_link       = $null
    last_started_at  = $null
    last_completed_at = $null
    last_error       = $null
}

if (Test-Path $statePath) {
    Write-Host ""
    Write-Host "Existing sync-state file found." `
        -ForegroundColor Cyan

    $loadedState = Get-Content `
        -Path $statePath `
        -Raw |
        ConvertFrom-Json

    if ($loadedState.mailbox_address -ne $mailbox) {
        throw (
            "The saved state belongs to a different mailbox: " +
            $loadedState.mailbox_address
        )
    }

    if ($loadedState.folder_id -ne $inboxFolderId) {
        throw (
            "The saved folder ID does not match the current Inbox. " +
            "Do not reuse a deltaLink across different folders."
        )
    }

    $state = $loadedState
}

$state.last_started_at =
    (Get-Date).ToUniversalTime().ToString("o")

$state.last_error = $null

# Save the attempted-start time without changing the existing deltaLink.
$state |
    ConvertTo-Json -Depth 10 |
    Set-Content `
        -Path $statePath `
        -Encoding UTF8

# ------------------------------------------------------------
# 7. CHOOSE INITIAL OR INCREMENTAL MODE
# ------------------------------------------------------------

if (
    [string]::IsNullOrWhiteSpace(
        $state.delta_link
    )
) {
    $syncMode = "INITIAL_BASELINE"

    $currentUri = (
        "https://graph.microsoft.com/v1.0/users/" +
        $encodedMailbox +
        "/mailFolders/inbox/messages/delta" +
        "?%24select=" +
        "id,subject,from,toRecipients,ccRecipients," +
        "receivedDateTime,bodyPreview,hasAttachments," +
        "conversationId,internetMessageId,isRead," +
        "parentFolderId,lastModifiedDateTime"
    )
}
else {
    $syncMode = "INCREMENTAL"

    # Use the saved deltaLink exactly as returned by Graph.
    $currentUri = $state.delta_link
}

Write-Host ""
Write-Host "Sync mode: $syncMode" -ForegroundColor Cyan

# ------------------------------------------------------------
# 8. FOLLOW ALL NEXT LINKS UNTIL DELTA LINK
# ------------------------------------------------------------

$changes = [System.Collections.Generic.List[object]]::new()

$pageNumber = 0
$finalDeltaLink = $null

try {
    while (
        -not [string]::IsNullOrWhiteSpace(
            $currentUri
        )
    ) {
        $pageNumber++

        Write-Host ""
        Write-Host "Fetching delta page $pageNumber..." `
            -ForegroundColor Yellow

        $response = Invoke-RestMethod `
            -Method Get `
            -Uri $currentUri `
            -Headers $headers

        $pageItems = @($response.value)

        Write-Host (
            "Items returned on this page: " +
            $pageItems.Count
        )

        foreach ($message in $pageItems) {
            $propertyNames =
                $message.PSObject.Properties.Name

            $wasRemoved =
                $propertyNames -contains "@removed"

            $removedReason = $null

            if ($wasRemoved) {
                $removedReason =
                    $message.'@removed'.reason
            }

            $senderName = $null
            $senderEmail = $null

            if ($null -ne $message.from) {
                $senderName =
                    $message.from.emailAddress.name

                $senderEmail =
                    $message.from.emailAddress.address
            }

            $toAddresses = (
                @($message.toRecipients) |
                ForEach-Object {
                    $_.emailAddress.address
                }
            ) -join ";"

            $ccAddresses = (
                @($message.ccRecipients) |
                ForEach-Object {
                    $_.emailAddress.address
                }
            ) -join ";"

            $changeRecord = [PSCustomObject]@{
                sync_mode            = $syncMode

                # Standard delta does not necessarily say whether a
                # non-removed object was newly created or updated.
                # Treat it as an idempotent upsert.
                change_action        = if ($wasRemoved) {
                    "REMOVED_FROM_INBOX"
                }
                else {
                    "UPSERT"
                }

                graph_message_id     = $message.id
                internet_message_id  = $message.internetMessageId
                conversation_id      = $message.conversationId
                parent_folder_id     = $message.parentFolderId
                subject              = $message.subject
                sender_name          = $senderName
                sender_email         = $senderEmail
                to_recipients        = $toAddresses
                cc_recipients        = $ccAddresses
                received_at          = $message.receivedDateTime
                last_modified_at     = $message.lastModifiedDateTime
                body_preview         = $message.bodyPreview
                has_attachments      = $message.hasAttachments
                is_read              = $message.isRead
                removed_reason       = $removedReason
                observed_at          = (
                    Get-Date
                ).ToUniversalTime().ToString("o")
            }

            $changes.Add($changeRecord)
        }

        if (
            -not [string]::IsNullOrWhiteSpace(
                $response.'@odata.nextLink'
            )
        ) {
            # Continue this same synchronization round.
            $currentUri =
                $response.'@odata.nextLink'

            continue
        }

        if (
            -not [string]::IsNullOrWhiteSpace(
                $response.'@odata.deltaLink'
            )
        ) {
            # The current synchronization round is complete.
            $finalDeltaLink =
                $response.'@odata.deltaLink'

            $currentUri = $null
            break
        }

        throw (
            "Graph returned neither @odata.nextLink " +
            "nor @odata.deltaLink."
        )
    }

    if (
        [string]::IsNullOrWhiteSpace(
            $finalDeltaLink
        )
    ) {
        throw "The delta synchronization produced no final deltaLink."
    }

    # --------------------------------------------------------
    # 9. COMMIT THE NEW STATE ONLY AFTER THE FULL ROUND SUCCEEDS
    # --------------------------------------------------------

    $state.delta_link = $finalDeltaLink

    $state.last_completed_at =
        (Get-Date).ToUniversalTime().ToString("o")

    $state.last_error = $null

    $state |
        ConvertTo-Json -Depth 10 |
        Set-Content `
            -Path $statePath `
            -Encoding UTF8

    # --------------------------------------------------------
    # 10. EXPORT THIS RUN'S OBSERVED CHANGES
    # --------------------------------------------------------

    $changesArray = @($changes.ToArray())

    ConvertTo-Json `
        -InputObject $changesArray `
        -Depth 10 |
        Set-Content `
            -Path $changesJsonPath `
            -Encoding UTF8

    if ($changes.Count -gt 0) {
        $changes |
            Export-Csv `
                -Path $changesCsvPath `
                -NoTypeInformation `
                -Encoding UTF8
    }

    # --------------------------------------------------------
    # 11. DISPLAY THE RESULTS
    # --------------------------------------------------------

    Write-Host ""
    Write-Host "Delta synchronization completed." `
        -ForegroundColor Green

    Write-Host "Mode:              $syncMode"
    Write-Host "Pages processed:   $pageNumber"
    Write-Host "Changes returned:  $($changes.Count)"
    Write-Host "State file:         $statePath"
    Write-Host "Changes JSON:       $changesJsonPath"

    if ($changes.Count -gt 0) {
        Write-Host "Changes CSV:        $changesCsvPath"
    }

    Write-Host ""
    Write-Host "Observed changes:" `
        -ForegroundColor Cyan

    if ($changes.Count -eq 0) {
        Write-Host "No Inbox changes since the previous deltaLink."
    }
    else {
        $changes |
            Select-Object `
                change_action,
                subject,
                sender_email,
                received_at,
                has_attachments,
                is_read,
                graph_message_id |
            Format-Table `
                -Wrap `
                -AutoSize
    }

    Write-Host ""
    Write-Host "New deltaLink was saved successfully." `
        -ForegroundColor Green
}
catch {
    $errorDetails = Get-HttpErrorDetails `
        -ErrorRecord $_

    $state.last_error = $errorDetails

    # Keep the old deltaLink. Never advance sync state after
    # a partial or failed synchronization round.
    $state |
        ConvertTo-Json -Depth 10 |
        Set-Content `
            -Path $statePath `
            -Encoding UTF8

    Write-Host ""
    Write-Host "DELTA SYNCHRONIZATION FAILED" `
        -ForegroundColor Red

    Write-Host $errorDetails `
        -ForegroundColor Red

    if (
        $errorDetails -match "syncStateNotFound"
    ) {
        Write-Host ""
        Write-Host (
            "The saved delta token is no longer valid. " +
            "Archive the state file and perform a fresh baseline."
        ) -ForegroundColor Yellow
    }

    throw
}
finally {
    $accessToken = $null
    $tokenResponse = $null
    $headers = $null
}