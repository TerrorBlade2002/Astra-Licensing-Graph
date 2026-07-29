# Milestone 4 staging acceptance

Use synthetic correspondence only and retain screenshots/log correlation IDs.

1. Sign in through PKCE; verify `/auth/me`, tenant/audience validation, wrong-tenant 401, unassigned 403.
2. Confirm Reader cannot mutate; Reviewer can decide; Manager can assign; Admin sees rules/evaluation.
3. Classify the synthetic RASI Colorado renewal/request fixture; confirm specific request type, canonical state/license, items, date, evidence, and mandatory review.
4. If AI is approved, confirm `store=false`, strict schema, redaction, no binary/tools/history, usage recording, and human review. Repeat with prompt-injection text.
5. Have two reviewers open one item; save from one and confirm the other receives 409.
6. Correct one field, inspect durable diff, approve, and create the task. Confirm requested items, route, due date, and `CLASSIFIED -> TASK_CREATED`.
7. Reclassify and confirm both versions and audit history remain.
8. Confirm no outbound draft row, Graph send/draft request, mailbox movement, or regulator automation occurred.
