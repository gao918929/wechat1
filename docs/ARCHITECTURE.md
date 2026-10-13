# Architecture and invariants

## Request and planning paths

```text
WeChat mini program / local browser verification console
    |  Bearer-authenticated HTTPS
FastAPI API ---- SQLite WAL (sessions, groups, members, versioned entities, durable events)
    |             | atomic receipts / inventory / meal deductions
    |             | owner/group authorization on every route
    v
Persistent queued planning job
    -> independent Inventory / Health / Iteration LLM calls in parallel
    -> independent Budget/composer LLM call
    -> strict schema and canonical ingredient IDs
    -> expiry-aware first-expiring-first-out inventory allocation
    -> per-diner nutrition recomputation and hard-exclusion check
    -> price lookup and procurement budget recomputation
    -> up to 3 targeted repair calls
    -> fresh-input comparison -> safe results, events and in-app notification
```

## Files

- `schemas.py`: Pydantic request and model-output contracts; extra fields prohibited, numeric bounds enforced.
- `store.py`: transaction context, SQLite schema, ownership scopes, versioned records and durable events.
- `domain.py`: audited catalog lookup, prices, target calculations, inventory consumption, multi-plan validation.
- `provider.py`: independent real provider calls, bounded retries, JSON and SSE parsing; no embedded model key or runtime fake.
- `recognition.py`: private drafts, EXIF stripping, size bounds, confidence and reference-weight estimates.
- `services.py`: idempotent receipt/meal workflows and weekly memory summaries.
- `orchestrator.py`: queue consumption, independent calls, validation, bounded regeneration and restart semantics.
- `main.py`: authentication, authorization, business endpoints, SSE, WebSocket and static verification UI.

## Persistence and concurrency

Every mutation uses a short `BEGIN IMMEDIATE` transaction. Network calls occur outside database transactions. Inventory updates require an expected version; concurrent changes return 409. Consumption aggregates duplicate lines before checking available mass and rolls the whole transaction back on failure. Receipt confirmation and associated inventory/prices commit together.

Idempotency IDs are namespaced by group, owner and operation. Reusing an ID with different input returns 409. A recognition draft can be confirmed once; changing the idempotency key cannot import it twice.

The queue is durable but designed for one process/worker. Browser or mini-program disconnect does not cancel the worker. A server restart marks an interrupted running task failed instead of silently issuing chargeable model calls again. Queued tasks can resume. Events replay by SSE ID. Rate limits are process-local and are not a distributed denial-of-service solution.

## Privacy

Sessions are random tokens stored as hashes with expiration. WeChat session secrets/openids are not returned to clients. Development login is explicitly gated and loopback-only. Group invite codes are random and stored hashed; rotating a code invalidates the old one.

Personal profiles and twins are owner-only. The planner reads other participating members' necessary dietary constraints/targets but not their body measurements or private feedback. Jobs/results remain private until an explicit selected variant is shared. WebSocket messages are invalidations rather than whole private records. Group twins include only opted-in preferences. Original recognition images are not stored.

## Limitations worth preserving in deployment reviews

- SQLite schema v1 has an initial schema version marker; future migrations must be explicit. There is no pretend PostgreSQL cluster.
- No distributed job lease or horizontal-worker coordination.
- No raw model text displayed before validation. Streaming is safe stage/daily-result streaming, not unsafe token echo.
- No cross-contact or hidden-ingredient guarantee. Text-only cooking instructions are screened for known forbidden aliases, but cannot prove food safety.
- No immutable ledger reversal/correction workflow yet. Do not manually rewrite expense rows to disguise errors.
- No external WeChat subscription push, clinically validated health score, automated acquisition of licensed datasets, or measured food-photo accuracy.
- Authenticated users may initiate billable AI work; tune quotas and use dedicated scoped API credentials before wider access.
