# Implementation and acceptance matrix

Date: 2026-10-13. Branch: `gpt`. The V3.1 source specification is kept unchanged.

**This is an implemented, locally tested first release, not a claim that every V3.1 requirement has completed production acceptance.**

| Specification area | Implemented path | Acceptance / remaining work |
|---|---|---|
| 4.1 Ingredient inventory | Manual entries, image/text drafts, confirmation, versioned edits, category alerts, FEFO allocation, atomic consumption | Automated API tests. Recognition accuracy and real-photo calibration not measured. User-confirmed expiry required; no universal shelf-life guarantee. |
| 4.1 Reference estimation | Linear image ratio cubed × reference mass; explicit estimate flag, broad ±50% uncertainty, manual correction | Geometric heuristic, not a trained mass estimator. Unlike the sample ±15% in the spec, no unjustified accuracy claim. Per-user median correction factors are retained and applied to future reference estimates; this is a bounded heuristic, not a trained model. |
| 4.2 Receipts / budgets | Immutable confirmed paid amount, line discount allocation, exact historical price priority, estimated reference fallback, per-person / total budgets, reports | Tests cover replay, rollback, allocation and exact-vs-estimated prices. City price feeds are not bundled; users enter sourced local prices. Ledger correction/reversal workflow remains future work. |
| 4.3 Dietary groups / split meals | Nine model families in wiki, tags, hard/soft constraints, conditional recipient labels, deterministic per-diner validation | Requires explicit profiles/targets. Arbitrary natural-language medical claims are not a substitute for structured hard constraints. Complex cultural preferences rely partly on AI and user review. |
| 4.4 Health metrics | Private height/weight/age/body-fat/goals; optional adult reference formula; manual or imported target standards | No automatic adult formula for pregnancy, lactation, children or chronic conditions. Not a medical assessment. |
| 4.5 Preference memory | Explicit preferences, feedback, substitutions, corrections and selections used in future calls | Personal correction factors are applied conservatively; no trained vision model or measured accuracy claim. |
| 4.6 Collaboration | Groups, rotating hashed invite codes, admin/member roles, WebSocket invalidation, shared selected plans | API and WebSocket tests; no mobile-network load test. |
| 4.7 Nutrition / reports | Source-tagged calories/macros/micronutrients, recorded-intake trends, expenses, personal/group views, transparent target-alignment metric | Missing data not converted into fabricated values. Custom alignment metric is NOT a validated clinical health score. |
| 4.8 Shopping | Subtract valid inventory on planned dates, group by category, exact/estimated prices, text copy and mini-program canvas export | API/static tests; actual WeChat canvas export needs device testing. |
| 4.9 Post-meal review | Recognition draft, home/out context, manual edits, confirmed deduction, next plan receives recent intake | Automatic modification of an already selected future plan is deliberately NOT silent; regenerate to apply changed input. |
| 4.10 Digital twins | Weekly lazy refresh, private personal memory, configurable group visibility, shared-only feedback, withdrawal invalidation | Refresh occurs on next read rather than a hosted weekly cron. Some habits (precise cooking difficulty, shopping-channel inference) are not inferred automatically. |
| 5.1 True multi-agent | Three independent concurrent calls plus independent Budget/composer call; independent prompts and contexts | Architecture exercised with test-only fixtures. Live account calls not run without user credentials. |
| 5.2 LLM Wiki | Structured Markdown, bounded retrieval, source-aware catalog, importable licensed standards | Initial content is small and expandable. China tables / DRIs licensed datasets not supplied. |
| 5.4 Multiple plans | 2–3 valid modes, balanced required, explained trade-offs, selection-history ranking | Actual model quality and conflict diversity need live evaluation. |
| 5.5 Validation / retry | Schema + inventory/date allocation + per-diner nutrition + budget; up to three targeted repairs | Automated positive/negative tests. Health-first budget exception is explicit; no allergy exception. |
| 5.6 Streaming / background | Provider SSE, safe progress events, validated daily output, durable job/events, client polling fallback | Raw unsafe model text is not displayed before validation. Disconnect-safe; single-worker limit documented. |
| Notifications | Persistent owner-only in-app notifications | WeChat subscription-message adapter not implemented; requires template ID and user subscription consent. |
| 6 Deployment / runnable code | Native mini program, backend, local verification UI, Docker config, launch scripts, CI | Dependency install and local automated tests performed. Docker image and WeChat official compiler/device not yet run. |
| 6.6 Demo video | Reproducible script in `docs/DEMO.md` | Full genuine model-to-mini-program video NOT recorded; do not substitute test fixtures as real AI output. |

## Intentional safety interpretations

1. Allergens and explicit contraindications override all other goals, including special-population nutrition, resolving the wording conflict in Sections 4.3.4 and 5.4 of the specification.
2. “Visual freshness” is an observation, never evidence of microbiological safety.
3. AI output is never authoritative for paid amounts, prices, macros or permissions.
4. An unsupported model, missing price, unknown ingredient or missing special-population target causes an actionable error, not invented data.
5. Changing profile/inventory/price inputs invalidates stale plan selection.
6. Costs are incremental shopping costs; already-owned inventory is not booked as new spending.

## External acceptance checklist

- [ ] Set actual DeepSeek text/vision credentials and run independent calls, receipt OCR, food images and full weekly generation.
- [ ] Confirm token usage, latency, quota errors, provider truncation and retry costs on the configured account.
- [ ] Configure real WeChat AppID/secret, HTTPS/WSS domains, developer-tool compilation and at least one real device.
- [ ] Test multi-member cooperation with independently authenticated users.
- [ ] Import licensed China Food Composition / DRIs data and review population models with a qualified professional.
- [ ] Implement/approve a WeChat subscription template if external completion push is required.
- [ ] Record the actual end-to-end demonstration video.
- [ ] Production privacy/security/accessibility review, backups and dependency audit.
