# Persistence query shapes

| Read | Predicate/order | Supporting database key/index |
|---|---|---|
| Published queue page | immutable queue ID, rank > cursor, rank ASC, LIMIT <= 500 | unique `(queue_id, rank)` btree |
| Scoped case inbox | trusted scope, state, assignee | `(access_scope, state, assignee)` |
| Subject history | subject key, time | `(subject_key, created_at)` |
| Case review history | case ID, time | `(case_id, created_at)` |
| Audit trail | entity reference, time | `(entity_reference, created_at)` |
| Runnable/expired jobs | state, lease expiry | `(state, lease_expires_at)` |
| As-of labels | subject, known-at | `(subject_key, known_at)` |

Queue members have a primary key `(queue_id, record_key)` and unique `(queue_id, rank)`. Composite FKs also require membership's queue/run and score/run/record to agree. A queued page reads a bounded immutable membership set; it never re-sorts all scores. Queue ID identifies one published version. Later API code must authorize that queue/cohort before calling this internal repository.

The integration fixture creates 10,000 synthetic scores/members, analyzes the membership table and runs `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` on a rank-5000 cursor with LIMIT 50. It checks 50 actual returned rows and index use; the complete plan is saved as `synthetic_queue_explain` in verification JUnit XML. This validates the query shape, not the architecture's API p95 or full scoring performance targets. Hardware/load/API benchmarks remain later phases.

Do not index wide feature JSON or every mutable field. Add source/partition/epoch/sequence and account/event-time indexes with the actual Phase 11 event/reconciliation schema and measured query shapes, not speculative empty event tables now.
