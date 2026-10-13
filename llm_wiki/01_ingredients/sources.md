# Ingredient knowledge and provenance

The initial catalog contains 19 USDA FoodData Central SR Legacy records downloaded via the official public API on 2026-10-13. `backend/data/ingredients.json` retains FDC IDs, original English descriptions, per-100-g nutrients, source URLs and retrieval dates. `backend/data/usda_raw.json` preserves the original response for auditing. These are data, not demo user inventories.

Values are per 100 g of RAW EDIBLE ingredient, except items inherently consumed as sold (milk, oil). Whole-item gross weight, cooked weight and edible raw weight are not interchangeable. Cooking yield, edible fraction, retention and individual product differences are not silently guessed. Unknown nutrient values remain null, never zero.

Allergen metadata is conservative ingredient-level classification, not a cross-contact guarantee. Read product labels; certification cannot be inferred from a photograph. Chicken/pork in the initial catalog are NOT marked halal-compatible. Users must import verified certified products separately when needed. Oats do not constitute a certified gluten-free product.

The China Food Composition Tables and Chinese DRIs are required external authoritative inputs for China-specific targets. They are not bundled or fabricated. Use `scripts/import_reference.py` with legitimately obtained, normalized data and exact source/provenance. Without these datasets the UI identifies USDA data and adult estimates honestly.

Official source: https://fdc.nal.usda.gov/api-guide
