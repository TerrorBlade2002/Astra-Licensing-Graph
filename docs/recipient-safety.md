# Recipient safety

The default mode is `REPLY`. Graph creates the reply draft and the application persists the actual Graph-generated recipient instead of assuming the inbound sender is the reply target.

`REPLY_ALL` is disabled by default. When enabled, a reviewer must explicitly select it, review every generated recipient, and set the plan's reviewed flag. Manual recipient changes require a reason, create a revision, and invalidate approval.

BCC is disabled by default. A Manager must authorize BCC for the individual plan with a reason, and startup rejects BCC without an explicit policy flag. Invalid or blocked addresses, empty To lists, excessive recipient counts, unreviewed reply-all, and unauthorized BCC block submission and send. Enabled `recipient_policy_rules` are evaluated by priority for allowed/blocked domains and addresses, internal-only restrictions, Manager requirements, recipient maxima, BCC, and reply-all. The send worker re-evaluates policy before the Graph POST. Send approval always displays the exact final list and external domains.

Admins manage validated rules through `/api/v1/admin/recipient-policies`; create and update operations are audited. A policy update cannot silently grandfather an already approved message because the send worker evaluates the current enabled registry immediately before Mail.Send.
