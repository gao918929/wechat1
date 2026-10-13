# Data conventions and provenance

## Initial food data

`backend/data/usda_raw.json`: original official FoodData Central API records retrieved 2026-10-13. `ingredients.json`: normalized subset of 19 records. The raw record names, FDC IDs, units and nutrient values are retained. They are not randomly generated fixtures.

No actual user inventory, price, receipt, budget transaction, or meal is pre-seeded. Dietary templates contain no stored plan answers.

Nutrition is per 100 g RAW EDIBLE portion. Unit fields: kcal, grams of protein/carbs/fat, mg calcium/iron/sodium/vitamin C. Missing micronutrients stay null. Cooked meal image estimates require user adjustment to equivalent raw edible portions; cooking retention/yield is not modeled.

Categorical allergens / vegetarian / halal compatibility are manually curated metadata, not certification. Product labels and contamination risks still require checking. Any imported override keeps existing known allergen flags as a conservative union.

## Licensed food table import format

```json
[
  {
    "id": "your_verified_ingredient_id",
    "name": "Local display name",
    "name_en": "Exact source description",
    "category": "vegetables",
    "allergens": [],
    "vegetarian": true,
    "halal_compatible": true,
    "near_expiry_days": 1,
    "aliases": [],
    "per_100g": {
      "kcal": 0,
      "protein": 0,
      "carbs": 0,
      "fat": 0,
      "calcium_mg": null,
      "iron_mg": null,
      "sodium_mg": null,
      "vitamin_c_mg": null
    },
    "source": "Exact publication, edition, table and record",
    "source_url": "https://your-authoritative-source.example/record",
    "retrieved_on": "2026-10-13"
  }
]
```

**The zeros above illustrate field types, NOT valid example food values. Replace every value with the verified source data.** A source link alone is not authenticity verification. The importer checks structure, finite non-negative numbers and provenance fields, not scientific truth or licensing rights.

## Target-standard import format

Each row has `age_min`, `age_max`, `sex` (`female`/`male`/`any`), exact `tags`, `meal_target`, `source`, `source_url`, `retrieved_on`. `meal_target` has eight non-negative ranges: `kcal_min/max`, `protein_min/max`, `carbs_min/max`, `fat_min/max`. These are **per meal**, not daily targets; document any professionally approved daily-to-meal allocation in the source field. Exact tag matching prevents a general adult row from applying to a pregnant or child profile.

Direct user-confirmed targets take precedence; applicable imported standards come next. Otherwise only fully specified ordinary adult profiles may use the explicitly labeled Mifflin–St Jeor reference formula. It uses a fixed light-activity multiplier 1.4 and dinner share 35%, and broad ranges. This is an implementation assumption, not a claim of Chinese DRIs compliance or an individualized treatment prescription.

Formula provenance: Mifflin MD et al., *A new predictive equation for resting energy expenditure in healthy individuals*, American Journal of Clinical Nutrition, 1990;51(2):241–247, DOI: `10.1093/ajcn/51.2.241`.

## Actual payments and price history

- Integer CNY fen: 1 CNY = 100 fen.
- Receipt `paid_cents` is immutable and explicitly confirmed.
- If all line totals are known, allocate paid amount proportionally; largest-remainder rounding preserves the exact sum.
- A missing line amount prevents claiming exact historical per-item prices for that receipt.
- Estimated weights never create exact historical unit prices.
- Procurement costs round up to integer fen; per-person displays also round up and may differ slightly from a precise division.
- Category spending remains `unallocated` when line data cannot support a truthful split.
- Database IDs, versions, owners and group IDs are controlled by the server, not by model output.
