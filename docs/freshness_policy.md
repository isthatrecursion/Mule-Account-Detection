# Freshness and unavailable assessments

Policy: `freshness_v1` · Owner: operator, with fraud_operations review · Agreement pending.

Persist independent fields: `completeness` (`COMPLETE`, `INCOMPLETE`, `UNKNOWN`), `freshness` (`COMPLETE`, `BUFFERING`, `PROVISIONAL_HIGHER`, `STALE`, `UNAVAILABLE`), and append-only publication events (`RECONCILED`, `CORRECTED`). The architecture's seven visible terms are preserved without conflating an event with evidence of completeness.

| Term | Meaning and display |
|---|---|
| COMPLETE | Required source sequences, counts, heartbeats and watermarks cover the assessment's feature windows; display assessed-as-of time. Research snapshots can be complete only against their declared snapshot contract; never claim live transaction coverage. |
| BUFFERING | Source gap within 600 seconds; retain last complete baseline and warning. |
| PROVISIONAL_HIGHER | Incomplete evidence raises review priority; separate flagged overlay retains baseline, source coverage and uncertainty. |
| RECONCILED | Publication event after late-event reconstruction and completeness checks; new immutable score version, linked to old baseline/events/model/feature state. |
| STALE | Gap exceeds 600 seconds; alert operations and retain original baseline time. |
| CORRECTED | Publication event for post-closure corrections/reversals, retaining prior lineage; reopen by authorized policy. |
| UNAVAILABLE | No complete historical baseline exists; nullable raw score, rank and percentile, explicit unavailable message. |

Every score response includes `assessed_as_of`, `published_at`, `source_coverage`, current `freshness`, `completeness`, baseline score-version ID and applicable publication event. UTC timestamps are timezone-aware; local display states its timezone. Coverage records required sources/partitions, window `[start,end)`, expected/received counts, watermark, sequence-gap/heartbeat evidence and coverage contract. Unknown coverage remains unknown.

During an outage, returning the prior baseline preserves its original `assessed_as_of` and `published_at`; a response-generation time cannot replace either. Provisional evidence has its own version, timestamps and incomplete coverage. Partial evidence may raise review priority but cannot lower or close the complete baseline. Resolve an unknown-scope source gap conservatively across every dependent window until impact is known.

If a new account appears during an outage, return `raw_score: null`, `rank: null`, `percentile: null`, `assessed_as_of: null`, `published_at: null`, `freshness: UNAVAILABLE`, `completeness: UNKNOWN`. A non-null provisional escalation, if any, appears separately and never masquerades as the baseline. Never show score zero, low-risk language or a complete timestamp for a missing baseline. An UNAVAILABLE account is not ranked in the complete cohort.

Reconcile on arrival and at least every 60 seconds, including events outside the grace interval. Late data is never discarded solely for being older than ten minutes. Publish features, score and audit atomically; incomplete reconstruction cannot emit a COMPLETE assessment. These rules are specifications for P02.08, P08, P11 and P12, not a claim of a working reconciler.
