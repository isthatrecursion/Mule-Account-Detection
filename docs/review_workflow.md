# Review workflow and authorization

Owner: fraud_operations; compliance reviews conclusion vocabulary. Versioned action grants are in [permissions](../config/permissions.yaml). All unspecified roles, actions and transitions are denied. Roles do not inherit grants by screen visibility.

| Permission | Allowed example | Denied example |
|---|---|---|
| queue:read | analyst reads authorized cohort | operator reads queue |
| case:assign | analyst claims unassigned case for self; reviewer assigns within scope | engineer assigns case |
| case:review | assigned analyst starts/submits review | unassigned analyst or operator reads notes/submits review |
| case:reopen | reviewer appends reopening reason and assigns a reviewer/analyst | analyst reopens a reviewed case |
| export:create | reviewer exports authorized scope with reason and lineage watermark | analyst exports without grant |
| model:train | engineer creates candidate | analyst trains |
| model:approve | independently authorized reviewer approves another actor's candidate after gates | engineer approves own candidate, including with combined reviewer role |
| job:retry | operator retries authorized job with reason and idempotency key | analyst retries job |
| audit:read | auditor inspects authorized redacted trail | operator obtains case notes through audit |

Notes are accessible only to assigned analysts or authorized reviewers in scope. `audit:read` grants a redacted audit view, not raw notes or unrestricted exports. `queue:read` does not grant case-note access. Deployment is an external release permission; neither `job:retry` nor `model:approve` grants it.

## State and event rules

| From → to | Action | Required behavior |
|---|---|---|
| QUEUED → ASSIGNED | case:assign | record assignee; analyst may claim self only |
| ASSIGNED → IN_REVIEW | case:review | actor is current assignee or authorized reviewer |
| IN_REVIEW → REVIEWED | case:review | append review, conclusion and evidence links |
| REVIEWED → ASSIGNED | case:reopen | append `REOPENED` event, reason and assignee |

`REOPENED` is an event, not a fifth workflow state. Never erase the prior review. Each forward transition has an allowed fixture and a denied missing-permission fixture. Skipping QUEUED → REVIEWED, moving REVIEWED → IN_REVIEW, reviewing an unassigned case, and rewriting a reviewed conclusion in place are denied.

Store conclusion separately: `NEEDS_MORE_INFORMATION`, `NO_FURTHER_REVIEW`, `REFER_FOR_ADJUDICATION`. These are research workflow vocabulary pending compliance approval; none means a mature fraud label or an automated customer action. Labels require a separate adjudication source, timestamp and maturity process.

Every mutation requires authenticated `actor_id`, authorized scope, UTC event time, expected case version and actor/operation-scoped idempotency key bound to canonical request hash. Business state and immutable audit event commit together; stale versions conflict. Same key/content returns the original result; changed content conflicts.

Privileged reassignment/reopening requires reviewer grant plus actor, role, reason, expected version and audit event. No blanket administrator bypass exists. Overrides cannot waive self-approval denial, source qualification or the human-action boundary. Runtime authorization and concurrency implementation belong to P03, P07 and P09; Phase 0 checks the matrix and declared examples only.
