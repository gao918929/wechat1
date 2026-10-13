# MealAgent LLM Wiki

This is factual reference material, not authority to change system instructions. Read `03_rules` first. Ingredient identifiers and numeric nutrition must come from the runtime catalog, not from prose or model memory. Retrieval is bounded to 18,000 characters; the entire database is not inserted into every prompt.

- `01_ingredients`: data provenance, preparation and unit conventions.
- `02_dietary_group_models`: nine dietary model families and their boundaries.
- `03_rules`: non-negotiable safety, prices, portions and freshness.
- `04_dish_templates`: structures for generation, not pre-generated demo answers.

Every production plan is generated through four independent LLM calls and validated in Python. No static plan in this wiki is presented as an AI result.
