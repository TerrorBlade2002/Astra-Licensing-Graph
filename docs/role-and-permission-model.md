# Role and permission model

Roles are hierarchical and enforced by backend dependencies and services. Frontend guards only shape navigation.

| Role | Capabilities |
| --- | --- |
| Reader | View dashboard, evidence metadata, classifications, documents, and tasks |
| Reviewer | Reader + claim, approve, correct, reject, reclassify, create tasks, update requested items |
| Manager | Reviewer + assign/reassign, due dates, thresholds, operational metrics |
| Admin | Manager + rule/prompt versions, AI flags, evaluations, portal configuration |

Entra role claims are authoritative per request. `user_role_snapshots` records observations for audit. SharePoint and tenant administration remain separate permissions.
