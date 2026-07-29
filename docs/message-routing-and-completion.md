# Message routing and completion

Response-required source messages move only after `SENT_COPY_VERIFIED`. `NO_RESPONSE_REQUIRED` plans may move without a draft after their plan is reviewed. The default `TASK_DESTINATION` policy uses the task's verified Graph folder; optional `COMPLETED_FOLDER` must be explicit per environment.

For `NO_RESPONSE_REQUIRED`, plan creation and the durable move job are committed together. A Manager destination override requires a reason plus an ID/name pair already verified for the source mailbox.

Move intent is persisted before Graph. A `201` response must contain a message ID and the exact destination parent folder ID. Move timeout is ambiguous and is reconciled by immutable source ID; the worker never repeats the move blindly.

Finalization locks the email, task, plan, draft, and verified move, transitions `TASK_CREATED -> MOVED -> COMPLETED`, stores the returned immutable Graph ID and destination, and creates completion, audit, processing, and outbox records atomically. Only the email intake/routing workflow completes. The licensing task status and `completed_at` are deliberately unchanged.
