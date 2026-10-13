# Prices, expenses and portions

- Currency is CNY; immutable actual payments are stored as integer fen (CNY × 100).
- Expense tracking records the actual confirmed payment, NOT a meal cost estimate.
- If all receipt lines have known amounts, allocate the final paid total proportionally across lines using largest-remainder integer rounding. Record original line amounts and allocated paid amounts.
- Derive exact historical per-kg prices ONLY from confirmed measured weights and fully allocatable receipt lines. Never convert an estimated weight into an exact historical price.
- Exact historical prices take precedence over newer manually supplied market references. References are always marked estimated. Missing prices are not invented.
- Weekly planning budgets apply to incremental PURCHASES after stock allocation, not to already-owned ingredients. Shopping cost rounds up to whole fen. Show total and per-person values.
- A plan's ingredient weights are TOTAL raw edible grams for each dish. Split equally across that dish's intended recipients for validation. Every requested diner must meet their own meal targets each day.
- Stock is allocated first-expiring-first-out on each meal date and cannot be negative. Do not use a lot after its expiry or when marked visually not fresh.
- Reference-object weight = reference mass × linear dimension ratio³ is only an unverified shape/density heuristic. Always label it estimated and provide a broad uncertainty interval; never present it as measured mass. If unreliable, leave weight empty for user confirmation.
