# MealAgent: A Comprehensive AI-Powered Meal Coordination WeChat Mini Program · Project Design Document (Final)

**Version**: V3.1 Final Edition　**Date**: 2026-10-13　**Status**: All requirements confirmed; ready for development

---

## 0. Version and Revision History

| Version | Changes |
|---|---|
| V1.0 | Initial project concept finalized (first draft of 10 core functional modules) |
| V2.0 | Issue fixes and product upgrades (clarified budget definitions, shelf-life logic, conflict resolution, validation, and rollback) |
| V3.0 | Incorporated key user ideas (receipt-based expense tracking, reference-object size comparison, digital twins, and multiple dishes for different diners) |
| V3.1 | **Finalized**: All 13 open questions resolved; requirements frozen |

**Key Design Decisions (Basis for the Final Specification)**:

| Decision Area | Final Decision |
|---|---|
| Cost definitions | Expense tracking records the actual amount paid. Cost calculations prioritize historical actual purchase prices; when no history exists, use reference prices and label them “Estimated.” |
| Budget definition | Implement a **per-person budget** by default, with a simple UI switch to a total budget. Avoid complex configuration; finalize the demo presentation on-site. |
| Constraint hierarchy | Allergens are hard constraints (absolute veto); taste-based food avoidance is a soft constraint (the AI recommends avoidance, but users may override it). |
| Different dishes for different diners | **Triggered only when needed**: Enable differentiated meal options and “Suitable for” labels only when the group includes people with specific dietary needs (pregnant women / people with chronic conditions / children) or has conflicting soft constraints. In ordinary scenarios, default to a plan that accommodates everyone, without labels. |
| Multiple agents | **A genuine multi-agent architecture**: Each of the four agents makes independent LLM calls, orchestrated by a central scheduler. Do not simulate multiple agents within a single prompt. |
| Image recognition / LLM | Use **DeepSeek multimodal models** throughout (structured JSON output for image recognition, plus meal-plan generation). |
| Estimation strategy | When no receipt is available and the user has not provided exact information, estimate weight by comparing the ingredient with a reference object. **All estimates must be labeled “Estimated.”** |
| Knowledge base | Establish the LLM Wiki architecture first; determine the amount of content during development (the architecture must support full-scale expansion). |
| Privacy | Personal twins are viewable and editable only by their owners. Group-twin visibility is configurable (owner only / selected members / all members). |
| Deliverables | Locally deployed backend + cloud-based DeepSeek API + recorded demo video + genuinely runnable source code. |
| Generation mode | **Prioritize streaming output** (display results as they are generated). If a request times out or the user leaves, continue generation in the background and send a notification when complete. |
| Nutrition data | Use multiple standard sources: *China Food Composition Tables* + *Chinese Dietary Reference Intakes (DRIs)*, with support for expansion to USDA and other sources. |

---

## 1. Project Overview

### 1.1 One-Sentence Positioning

> China's first WeChat mini program for end-to-end, AI-powered automated meal coordination incorporating **dietary digital twins**—connecting “ingredient inventory + budgeting and expense tracking + dietary needs of different groups + health metrics + multi-agent weekly planning + post-meal review and iterative improvement.” AI makes recommendations, users make decisions, and the system understands its users better with continued use.

### 1.2 Three Core Innovations

1. **An end-to-end automated coordination loop**: Data drives six interconnected stages—inventory, budgeting, health, planning, shopping, and review—setting the system apart from standalone, single-purpose tools.
2. **Self-learning dietary digital twins**: Both personal twins and household/dormitory group twins continuously retain preferences, habits, and budgeting behavior, making plans increasingly tailored over time.
3. **Transparent decisions with multiple options**: Rather than forcing a single answer, the AI provides two or three plans in conflicting scenarios, explicitly explains the trade-offs, and leaves the final decision to the user.

### 1.3 Platform and Use Cases

- Platform: A WeChat mini program (no separate download, low barrier to entry, suitable for households and students living in dormitories).
- Scenario A: Shared meals for three to five dormitory students (shared inventory, multiple dietary preferences and restrictions, per-person budgets).
- Scenario B: Everyday household meals (health management, budget control, and ingredient freshness).

---

## 2. Core Design Principles

| Principle | Description |
|---|---|
| 1. AI recommends; people decide | All AI outputs are suggested plans. Safety requirements such as allergen avoidance are hard constraints; taste preferences are soft recommendations that users may override. |
| 2. Recognition assists; fallbacks come first; everything is editable | Recognition improves efficiency rather than replacing user control. All recognition results appear as “item-list cards,” supporting tap-to-edit changes and edits through AI conversation. |
| 3. Digital-twin memory improves understanding over time | Preferences, habits, budgeting behavior, and historical feedback are retained, with profiles updated weekly. |
| 4. Make conflicts transparent and offer multiple plans | When objectives conflict, do not hide the trade-offs. Show priorities and compromises, and provide several alternatives. |
| 5. Maintain clear boundaries and compliance | All dietary suggestions reference the *Dietary Guidelines for Chinese Residents*. They are general guidance and do not constitute medical advice. |

---

## 3. Competitor Analysis and Differentiation

| Existing Products | Critical Limitations | This Project's Approach |
|---|---|---|
| Recipes on Xiachufang / Xiaohongshu | Provide recipes without considering inventory, budgets, or users' health conditions. | Link data across the entire workflow; enter all constraints once and let the AI automatically match suitable options. |
| Refrigerator-management apps | Only warn about expiration; do not plan meals or account for nutrition. | Let inventory directly drive meal plans and require priority use of ingredients nearing expiry, moving from “warning you about expiry” to “helping you use ingredients up.” |
| Weight-loss and health apps | Only count calories, disconnected from ingredients available at home, making plans hard to implement. | Apply inventory, budget, and nutrition constraints simultaneously, producing plans that match available ingredients. |
| Grocery-shopping apps | Focus on selling products, without meal planning or dietary-avoidance checks. | Plan a week's meals first, then derive the shopping list and automatically exclude ingredients already in stock. |
| Ordinary AI recipe generation (single-turn conversations) | One-off generation, no long-term iteration, no multi-person support, and no memory. | Genuine multi-agent dynamic weekly planning + digital-twin memory + multi-person collaboration + review-driven iteration. |

---

## 4. Detailed Functional Design

### 4.1 Intelligent Refrigerator Inventory System (Foundational Module)

#### 4.1.1 Three Input Channels

1. **Photo-based recognition and inventory entry**: Take a photo of the refrigerator or ingredients; the AI identifies ingredient types and quantities and automatically adds them to inventory.
2. **Automatic entry from receipts**: Recognize shopping receipts or price labels and record ingredient names, prices, and purchase times in one operation (linked to budgeting and expense tracking).
3. **Manual / AI-conversation entry**: Enter information manually or through natural language (e.g., “There are still two eggs and half a head of Chinese cabbage in the refrigerator”).

#### 4.1.2 Reference-Object Ratio Estimation Engine (The “Comparison” Method)

**Principle**: Use built-in reference objects (an egg by default, approximately 50 g each and 4.5 cm in diameter). The AI identifies the pixel-size ratio between the reference object and the target ingredient to estimate the target's size, weight, or quantity. For example, when Chinese cabbage and an egg appear in the same image, use their relative dimensions to estimate the cabbage's weight.

**Conditions of Use (Final)**: Apply this method only when **no receipt is available and the user has not provided exact information**. Where a receipt includes measured weight or the user enters exact values manually, those exact values take precedence.

**Design Details**:

- Maintain a built-in reference-object library: eggs, common bottled water, standard dinner plates, etc. Users may also manually identify any known object in the image as a temporary reference.
- Output an **estimated range** (e.g., “Chinese cabbage: approximately 800 g ±15%”). **The word “Estimated” must appear** to distinguish estimates from exact data.
- Allow one-tap correction of all estimates. Write corrections to the digital twin so it remembers the actual sizes of ingredients commonly used by that user and automatically calibrates future estimates.
- Failure fallback: If the ingredient is identified but its weight cannot be estimated, display “Ingredient identified; weight required.”

#### 4.1.3 Two-Dimensional Freshness Alerts

| Dimension | Method | Description |
|---|---|---|
| Visual freshness | Image recognition detects wilted leafy vegetables, discoloration, darkening, and changes in meat color. | Dynamically adjust the expiry-risk level (visible loss of freshness takes precedence over time-based assessment). |
| Time tracking | Automatically extract the purchase date from a receipt; without a receipt, use the date the item was first added to inventory. | Set category-specific thresholds based on shelf life rather than applying uniform three- or seven-day rules. |

**Example Shelf-Life Table by Category**:

| Category | Example Shelf Life | Near-Expiry Threshold |
|---|---|---|
| Leafy vegetables | 2–3 days | 1 day remaining |
| Root and tuber vegetables (potatoes / carrots) | 2–4 weeks | 5 days remaining |
| Fresh meat (refrigerated) | 3–5 days | 1 day remaining |
| Frozen meat | 1–3 months | 7 days remaining |
| Eggs | 3–5 weeks | 5 days remaining |
| Dairy products | 1–2 weeks | 3 days remaining |

**Alert Levels**: Three levels—nearing expiry (based on category-specific thresholds), expired, and visibly not fresh.

#### 4.1.4 Two Paths for Deducting Inventory Usage

1. **Automatic path**: Post-meal photo review identifies ingredients used in the meal → automatically deduct them from inventory.
2. **Manual path**: Users select ingredients consumed that day or make changes through AI conversation (e.g., “I used two eggs today”).

> Inventory is the system-wide data foundation. Deduction workflows must have reliable fallbacks to prevent inaccurate inventory from undermining all subsequent planning.

#### 4.1.5 Recognition Output Format (Convenience Design)

All AI recognition results use a consistent **item-list card** format:

- Tap any recognized item to edit its name, quantity, weight, or shelf life.
- Edit the entire list through AI conversation (e.g., “Change the Chinese cabbage to 400 g” or “This is not baby Chinese cabbage; it is bok choy”).
- Add items to inventory after confirmation. Users are never forced to enter information manually, but can edit it at any time.

---

### 4.2 Budget Control and Intelligent Expense Tracking

#### 4.2.1 Three Price-Capture Channels

1. **Weighed-item price-label recognition (most complete information)**: Extract the product name, unit price (CNY/kg), weight, and total price in one operation.
2. **Shopping-receipt recognition (next most complete)**: Supermarket receipts contain item names, quantities, unit prices, and amounts line by line; simple market receipts may contain only item names and total prices.
3. **Regional reference-price database fallback**: When receipts or price labels are unavailable, use reference market prices for the user's city, with manual adjustment available.

#### 4.2.2 Expense-Tracking and Cost-Calculation Definitions (Final: Two Separate Concepts)

**In Plain Language**:

- **Expense tracking** = recording “how much was actually spent,” based on the **actual amount paid on the receipt**. This is the transaction ledger and must not be altered.
- **Cost calculation** = estimating “roughly how much this week's groceries will cost” **before** the AI plans a week's meals, to assess whether the budget will be exceeded.

**Price Priority for Cost Calculation**:

1. The user's historical actual purchase prices (retained from receipts; the most realistic source and used first).
2. No price history → regional reference prices, **labeled “Estimated.”**

**Tiered Completion of Missing Unit Prices**:

| Missing Data | Completion Method |
|---|---|
| Unit price missing; total price and weight available | Unit price = total price ÷ weight; calculate automatically. |
| Unit price missing; total price and quantity available | Estimate weight using a reference object → derive the unit price (label it “Estimated”). |
| Unit price and weight missing | Use the reference price by default, label it “Estimated,” and allow user edits. |
| All item details missing (handwritten total-only receipt) | Record only the total amount in the expense ledger; use reference prices for cost calculations and label them “Estimated.” |

#### 4.2.3 Budget Definition (Final: Keep Implementation Simple)

- Implement a **per-person budget by default** (suited to shared dormitory meals).
- Provide a simple switch to “Total budget”; avoid complex configuration.
- Decide which budget basis to use in the demo on-site after development is complete; this must not block development.

#### 4.2.4 End-to-End Budget Control and Expense Tracking

- Calculate ingredient costs in real time while the AI composes meal plans (prioritizing historical actual purchase prices); automatically substitute affordable ingredients if costs exceed the budget.
- Display total cost and per-person shares on the shopping list in real time, highlighting overruns.
- **Automatic expense tracking**: Each receipt or price-label recognition creates a food-expense record, categorized by ingredient type (vegetables / meat and eggs / seafood / staples / seasonings).
- Automatically generate weekly and monthly food-expense reports: total spending, category shares, per-person spending, and comparisons with the budget.
- **Price memory**: Store recognized prices in the digital twin and prioritize historical purchase prices in subsequent calculations.

---

### 4.3 Dietary Models for Different Groups and Shared-Meal Plans

#### 4.3.1 Nine Dietary-Group Models

Dormitory meals for university students (fat loss / muscle gain / saving money), balanced family meals, light stomach-friendly meals, management of high blood pressure / high blood glucose / high blood lipids with blood-sugar and fat control, pregnancy and lactation, child growth, high-protein fitness diets, vegetarian diets, and halal diets. All reference the *Dietary Guidelines for Chinese Residents*, automatically adjusting oil, salt, calories, and protein-to-carbohydrate ratios rather than retrieving ready-made recipes.

#### 4.3.2 Constraint Hierarchy: Hard vs. Soft Constraints (Final)

| Type | Definition | Handling |
|---|---|---|
| Hard constraints | Allergens (peanuts / seafood / mangoes, etc.) and dietary contraindications associated with chronic conditions. | Absolute veto: exclude them from every plan. |
| Soft constraints | Taste-based food avoidance (no fatty meat, no cilantro, no spicy food). | The AI avoids them by default and marks them “Recommended to avoid”; users may override this. |

> Design rationale (real dormitory scenarios): A does not eat fatty meat → choose lean cuts by default or separate lean and fatty portions when preparing the meat. B does not eat a particular vegetable → omit it by default or make a small portion; if someone particularly wants it, add a separate dish for that person. **The agent only ever makes recommendations; people make the final choice.**

#### 4.3.3 Two Shared-Meal Output Modes (Final: Triggered Only When Needed)

1. **Everyone-compatible plan (default)**: Use recipes that satisfy the group's common requirements, so everyone can eat every dish. **Do not include “Suitable for” labels.**
2. **Differentiated multi-dish plan (triggered when needed)**: Enable this **only when** the group includes people with specific dietary needs (pregnant women / people with chronic conditions / children) or has conflicting soft constraints:
   - Output two types of dishes: dishes the group wants to eat (labeled “Not eaten by [member] / Pregnant women are advised to avoid; suitable for others”) + dishes specifically for members with special needs (e.g., one or two dishes a pregnant member can and wants to eat).
   - Give every dish a “Suitable for” label. Users freely combine dishes for the shared table, ensuring both that the group has dishes it wants and that the pregnant member has dishes she can eat.

#### 4.3.4 Combining Multiple Tags

Support combinations such as “pregnant + blood-sugar control” and “fitness + stomach-friendly.” When conflicts arise, automatically apply priorities and explain the trade-offs.

**Priority Rule**: Nutritional needs of groups with specific requirements (pregnant women / people with chronic conditions / children) > allergen restrictions > taste-based food avoidance > inventory priority > budget constraints.

---

### 4.4 AI Planning Linked to Health Metrics

- Enter height, weight, body-fat percentage, and dietary goals (fat loss / muscle gain / maintenance / stomach-friendly eating).
- The agent automatically calculates daily total calorie targets and upper and lower limits for the three macronutrients (protein / carbohydrates / fat), then uses them to constrain each meal.
- Automatically filter out unsuitable ingredients high in oil or sugar.
- Include the following notice in every output: “This plan provides general dietary guidance and is not a basis for medical diagnosis. People with chronic conditions or specific dietary needs should follow medical advice.”

---

### 4.5 Food Avoidance, Allergens, and Preference Memory (Three-in-One)

- Manage allergens (hard constraints) and taste-based food avoidance (soft constraints) separately.
- Store preferences (liked / disliked foods, flavor intensity, and frequently eaten cuisines) in the digital twin.
- Automatically learn from every user modification to a meal plan (ingredient substitutions, deletions, portion adjustments) and write these changes to the profile.

---

### 4.6 Multi-Person Collaboration and Sharing System

- Share refrigerator inventory, shopping lists, dietary restrictions and preferences, and a pooled budget.
- Use backend WebSocket connections for real-time synchronization; one person's edits are synchronized to everyone.
- Tiered permissions: administrator (may edit inventory / budgets) and member (may mark consumption / submit requirements).
- Scenario: Four dormitory residents share the system. One person enters the refrigerator inventory, which everyone can view. A avoids spicy food and B avoids seafood; all preferences are recorded, and the AI produces a plan that accommodates everyone.

---

### 4.7 Nutrition Analysis and Data Visualization

- Daily and weekly calorie trends, statistics for the three macronutrients, and estimated vitamin and mineral intake.
- Dietary health scores and dietary-balance reports.
- Support individual views and overall group views (household / dormitory).
- **Nutrition Data Sources (Final: Multiple Standards)**: Use the *China Food Composition Tables* as the foundation and the *Chinese Dietary Reference Intakes (DRIs)* to set nutrient targets for different groups. Support expansion to international databases such as USDA for cross-validation. Attribute all data sources so their credibility can be demonstrated during the project defense.

---

### 4.8 Intelligent Shopping Lists

- After generating a week's meal plan, automatically compare it with inventory, exclude ingredients already available at home, and list only items that need to be purchased.
- Sort items by supermarket section (vegetables / meat / seafood / seasonings).
- Display total cost and per-person shares in real time, highlighting budget overruns.
- Export methods: one-tap text copying / shopping-list image generation (within the mini program's capabilities; local Excel export is not promised).

---

### 4.9 AI Post-Meal Photo Review (Closed-Loop Module)

- **Automatically distinguish dining contexts**:
  - Home-cooked meals: identify ingredients and portions → automatically deduct inventory and correct that day's nutrient-intake records.
  - Dining out / takeout: record nutrient intake only; do not alter inventory (to avoid disrupting the inventory baseline).
- Allow manual correction of recognition results and synchronize corrected data to the digital twin.
- Automatically fine-tune subsequent meal plans based on deviations in actual meals → form a complete “planning → execution → review → iteration” loop.

---

### 4.10 Dietary Digital-Twin System (Core Module)

#### 4.10.1 Positioning

A personalized dietary-profile system that continuously remembers preferences, habits, budgeting behavior, and historical feedback, enabling “one-time setup, long-term adaptation, and a better understanding of you with every use.”

#### 4.10.2 Memory Dimensions

**Personal Twin**:

- Taste preferences: liked / disliked ingredients, flavor intensity, frequently eaten cuisines, and maximum tolerated spiciness.
- Eating habits: mealtimes, portion patterns, preferred cooking difficulty, and frequently eaten dishes.
- Budgeting habits: acceptable price ranges, typical ingredient price tiers, spending frequency, and price sensitivity.
- Historical feedback: meal-plan ratings, favorites, deletions, and manual edits (including substitution preferences such as “replaced X with Y”).

**Household / Dormitory Group Twin**:

- Shared preferences, group-wide food avoidance, and patterns in the number of diners (weekday / weekend changes).
- Budget-sharing habits, usual shopping channels, and acceptable group price ranges.
- Union / intersection views of members' individual profiles (who avoids what, and who likes what).

#### 4.10.3 Learning Mechanism

| Feedback Type | Source |
|---|---|
| Explicit feedback | User ratings, favorites, deletions, and deliberate edits to meal plans. |
| Implicit feedback | Actual ingredient purchases, meal records, receipt prices, and corrections to recognition results. |
| Update cycle | Update profiles once a week to optimize the following week's plan. |

#### 4.10.4 Visibility and Permissions (Final)

- **Personal twin**: Visible only to its owner, who may edit it.
- **Group twin**: Configurable visibility—owner only / selected members / all members. Members may adjust the preference data they have contributed.
- Store data in a cloud database. Receipt images contain pricing information and are sensitive data; use them only for expense-tracking displays and do not share them externally.

#### 4.10.5 Value to the System

- Reduce repeated setup effort (from week two onward, users no longer need to re-enter constraints every time).
- In conflict scenarios, prioritize plans that match the user's historical choices.
- Automatically adapt to spending tiers and dietary styles, increasing plan acceptance with continued use.
- Provide the core data source for the Iterative Optimization Agent.

---

## 5. Multi-Agent Orchestration System (Core Innovation: Genuine Multi-Agent Architecture)

### 5.1 Overall Architecture (Final: Genuine Multi-Agent System)

**Central Orchestrator + Four Independent Agents + Shared Knowledge Base (LLM Wiki) + Three-Layer Validator**

> Final decision: **Each of the four agents makes independent LLM calls** (separate system prompts, separate contexts, and separate calls). The central orchestrator assigns tasks, collects results, and resolves conflicts. **Do not simulate multiple agents within a single prompt.**

```text
User's natural-language instruction
                 |
                 v
+--------------------------------------+
| Central Orchestrator                 | Parse intent, split tasks, schedule agents
| (Task Orchestrator)                  | Maintain global constraints, collect outputs,
+--------------------------------------+ and arbitrate conflicts
                 |
                 | Dispatch independent LLM calls sequentially / in parallel
       +---------+--------------+------------------+
       v         v              v                  v
 Inventory    Health          Budget           Iterative
 Priority     Adaptation      Constraint       Optimization
 Agent        Agent           Agent            Agent
(independent (independent     (independent      (independent
 LLM call)    LLM call)        LLM call)         LLM call)
       |         |              |                  |
       +---------+-------+------+------------------+
                         v
              Shared LLM Wiki Knowledge Base    Common factual basis for all agents
     (ingredients / nutrition / rules / dietary-group models / dish templates)
                         v
              Three-Layer Validator             Inventory -> nutrition -> budget
                         |                      On failure, return to the relevant
                         |                      agent for regeneration (up to 3 times)
                         v
              Multiple Plans (if conflicts)     Health-first / balanced / budget-first
                         |                      Twin-weighted ranking with trade-offs
                         v
              User Choice and Feedback          -> Write to digital twin
                                                -> Optimize next week's plan
```

**Costs and Mitigations of a Genuine Multi-Agent System** (prepare for questions during the project defense):

- Costs: high token consumption and longer generation latency (a complete weekly plan is expected to take 10–30 seconds or more).
- Mitigations: (1) streaming output reduces perceived waiting time; (2) asynchronous generation with completion notifications provides a fallback; (3) cache common results and reuse them directly for identical constraint combinations.

### 5.2 Knowledge-Base Layer: LLM Wiki (Structured Markdown Knowledge Base)

Build the knowledge base from structured Markdown documents, keep it manually maintainable, and supply it to the LLM to reduce hallucinations. **Architecture first; determine content volume during development** (the architecture supports full-scale expansion; several thousand ingredient records are not a problem for the LLM context—the key is how they are organized).

```text
llm_wiki/
├── 00_index.md                         # Knowledge-base directory and usage instructions
├── 01_ingredients/
│   ├── vegetables.md                   # Nutrition per 100 g, average shelf life,
│   │                                   # and reference price ranges
│   ├── meat_and_eggs.md
│   ├── seafood.md
│   ├── staples.md
│   └── seasonings.md
├── 02_dietary_group_models/
│   ├── fat_loss.md
│   ├── muscle_gain.md
│   ├── hypertension_hyperglycemia_hyperlipidemia_and_blood_sugar_control.md
│   ├── pregnancy_and_lactation.md
│   ├── child_growth.md
│   ├── light_stomach_friendly.md
│   ├── vegetarian.md
│   ├── halal.md
│   └── budget_dormitory_meals.md
├── 03_rules/
│   ├── conflict_priorities.md          # Priority rules in Section 4.3.4
│   ├── budget_calculations.md          # Price completion and basis definitions
│   ├── shelf_life.md                   # Category shelf lives and near-expiry thresholds
│   └── portions.md                     # Reference-object estimation and serving scaling
└── 04_dish_templates/
    ├── home_style_dishes.md
    ├── fat_loss_meals.md
    ├── quick_dormitory_dishes.md
    └── dishes_for_pregnant_women_children_older_adults.md
```

**Maintenance**: Manually maintained Markdown files with regular updates. Feed users' receipt data back into ingredient prices for calibration (actual prices override reference prices).

### 5.3 Responsibilities and Priorities of the Four Agents

| Agent | Core Objective | Responsibilities | Priority |
|---|---|---|---|
| Health Adaptation Agent | Nutritional and safety compliance | Use dietary-group models and health metrics to validate nutrient ratios and filter contraindicated ingredients. | 1 (highest) |
| Iterative Optimization Agent | Long-term user-experience improvement | Read digital-twin preferences and historical feedback; adjust dish styles and combinations. | 2 |
| Inventory Priority Agent | Minimize waste | Identify near-expiry and in-stock ingredients, require their inclusion in plans, and schedule them first. | 3 |
| Budget Constraint Agent | Keep costs under control | Calculate total cost (prioritizing historical actual purchase prices) and replace ingredients with affordable alternatives when over budget. | 4 |

### 5.4 Conflict Resolution and Multiple-Plan Output

1. **Non-negotiable baseline**: Health and safety issues such as allergens and dietary contraindications associated with chronic conditions have an absolute veto.
2. **Negotiable objectives**: Inventory use, budgets, and ordinary taste preferences may be traded off dynamically.
3. **Three-plan output rule** (automatically generate two or three plans in conflict scenarios, explaining each plan's trade-offs):
   - **Plan A — Health-First**: Strictly meet nutrition and food-avoidance requirements; may exceed the budget or leave some near-expiry ingredients unused.
   - **Plan B — Balanced**: Accommodate all objectives as much as possible for the best overall result (recommended by default).
   - **Plan C — Budget-First**: Strictly control costs; allow slight variation in some nutritional indicators.
4. **Twin-based weighting**: As historical choice data accumulates, automatically adjust the ranking of the three plans, presenting those that match user habits first.
5. Label every plan “Agent recommendation; freely adjustable.”

### 5.5 Three-Layer Validation and Rollback

The central orchestrator automatically validates results before output:

1. **Inventory validation**: Do the ingredients required by dishes match available inventory or items that can be purchased?
2. **Nutrition validation**: Are total calories and nutrients within the target thresholds?
3. **Budget validation**: Is the total cost within budget?

- Validation failure → return to the relevant agent for regeneration, with a maximum of three retries.
- Still failing → prompt users to adjust constraints (increase the budget / reduce food-avoidance restrictions / add inventory) and show which requirements have already been satisfied.

### 5.6 Generation Mode (Final: Streaming First, with an Asynchronous Fallback)

- **Prioritize streaming output**: Use SSE streaming to display the plan progressively during generation (overall framework first → daily dishes next → shopping list last). This reduces the impact of multi-agent latency and improves the defense demonstration.
- **Timeout / user leaves**: If the user leaves the page or the request times out, continue generation in the background. On completion, notify the user through WeChat subscription messages or in-app notifications so they can return to view the result.
- The demo environment may wait synchronously; the production environment uses both streaming and asynchronous channels.

---

## 6. Technical Architecture

### 6.1 Overall Architecture (Separated Frontend and Backend)

```text
+---------------------------------------------------------------+
| WeChat Mini Program (frontend interaction interface)           |
| Photo capture / item-list cards / chat input / result display  |
| Lightweight local cache                                       |
| (no large local databases or on-device AI models)              |
+-------------------------------+-------------------------------+
                                | HTTPS + WebSocket + SSE (streaming)
+-------------------------------v-------------------------------+
| Backend Services                                              |
| ├─ Business services: users / inventory / budgets / meal plans  |
| │                     / multi-person collaboration            |
| ├─ AI capabilities:                                           |
| │   ├─ Image recognition: ingredients / receipts / price labels|
| │   │                     / meals / freshness detection        |
| │   └─ LLM: multi-agent orchestration / meal-plan generation    |
| │           / conversational edits                            |
| ├─ Knowledge base: LLM Wiki (structured Markdown)              |
| └─ Data: users / inventory / budgets / twin profiles / expenses|
+---------------------------------------------------------------+
```

### 6.2 Mini-Program Responsibilities and Boundaries

- User interaction, photo capture, and result display.
- Lightweight local caching; no large databases (the mini program's local storage limit is 10 MB).
- **Do not run local AI models**; upload all images and text to the backend for processing.
- Export through text copying / image generation, within platform limitations.

### 6.3 Backend Service Components

- Business-service layer: user management, inventory management, budgeting and expense management, meal-plan management, and multi-person collaboration.
- AI-capability layer (see Section 6.4).
- Knowledge-base layer: LLM Wiki + retrieval-based context injection.
- Data layer: business data + digital-twin profiles.
- Real-time communication layer: WebSocket for real-time multi-person synchronization + SSE for streaming generation.

### 6.4 AI-Capability Layer: Unified Image Recognition and LLM (Final: DeepSeek Multimodal)

- **Image recognition**: Use **DeepSeek multimodal models** to produce structured JSON from ingredient photos, receipts and price labels, meal photos, and freshness assessments (ingredient lists / receipt fields / freshness labels / reference-object dimension information).
- **LLM**: Use the same model provider for multi-agent orchestration and meal-plan generation, keeping the stack unified and reducing integration costs.
- Business-layer post-processing: field validation, reference-object ratio estimation (dimension-ratio calculations), unit conversion, ingredient-database matching, and confidence labeling.
- Downgrade low-confidence results to “Awaiting user confirmation” cards; do not add them directly to inventory.
- Fallback plan: If DeepSeek vision produces unstable results on particular tasks (e.g., dense receipts), optionally add a dedicated OCR / image-recognition API as a backup (evaluate during development; not mandatory).

### 6.5 Data and Security

- Store user profiles, inventory, and expense data in the cloud.
- Personal twins are viewable and editable only by their owners; group-twin visibility is configurable (owner only / selected members / all members).
- Receipt images contain pricing information and are sensitive data. Use them only for expense-tracking displays and do not share them externally.

### 6.6 Deliverables (Final: Local Demo and Genuine Code)

- **Runtime environment**: Locally deployed backend services + cloud-based DeepSeek API.
- **Demo video**: Record the complete business workflow (natural-language instruction → weekly plan → shopping list → review and iteration).
- **Code submission**: Submit complete, **genuinely runnable** code (mini-program frontend + backend + knowledge base). **Fake or hard-coded demos are not allowed**—the Chuanzhi Cup requires code submission, and a live end-to-end demonstration may be requested during the defense.

---

## 7. Complete Closed-Loop Demo Script

**User's Natural-Language Instruction**:

> “I'm trying to lose body fat. I'm 175 cm tall and weigh 72 kg. There are four people in our dormitory, and our food budget this week is CNY 80 per person. I don't eat spicy food or seafood. We have tomatoes, eggs, and chicken breast that's about to expire in the refrigerator. Please plan a week's fat-loss dinners for us.”

**Fully Automated Agent Workflow**:

1. Read inventory: identify near-expiry chicken breast, tomatoes, and eggs, and mark them as the highest-priority ingredients to use.
2. Load constraints: match the fat-loss dietary model (high protein, low carbohydrates); exclude spicy food and seafood (mark these as overridable soft constraints); scale portions for four people.
3. Multi-agent collaboration (genuine independent calls): the Inventory Agent schedules near-expiry ingredients within the first three days; the Health Agent validates calories and protein for each meal; the Budget Agent calculates total cost against CNY 80 per person; the Iterative Agent references the dormitory's historical preferences.
4. Detect conflicts: no hard conflicts → output the “Balanced” main plan, with “Tighter Budget” and “Higher Protein” alternatives.
5. Shopping list: compare with inventory and exclude available ingredients; list required purchases by supermarket section, showing total cost and per-person shares.
6. Supporting outputs: daily calorie reports, projected weekly nutrient intake, and dietary health scores (with data-source attribution).
7. Set up the feedback loop: post-meal photo review → write data to the digital twin → automatically optimize the following week's plan.

---

## 8. Core Competitive Advantages (Defense Talking Points)

1. **The only end-to-end automated closed loop**: Fully connect inventory, budgeting, health, planning, shopping, and review, with genuine multi-agent automated coordination.
2. **Self-learning dietary digital twins**: Continuously remember preferences and habits, improving accuracy with continued use.
3. **Conflict-friendly decisions with multiple plans**: Do not force a single solution; make trade-offs transparent and accommodate complex real-world scenarios.
4. **Receipt-driven budgeting and expense tracking**: Photos automatically synchronize prices and inventory, addressing inaccurate pricing and the burden of manual bookkeeping.
5. **Reference-object estimation engine**: Address the difficulty of recognizing loose fresh ingredients without weight data.
6. **Deep support for multi-person scenarios**: Hard / soft constraint separation + everyone-compatible / differentiated multi-dish modes (triggered when needed) + group twins.

---

## 9. Risks and Scope Boundaries

1. **Medical boundary**: All dietary suggestions reference the *Dietary Guidelines for Chinese Residents*. They provide general health guidance, do not constitute medical advice, and cannot replace doctors or nutrition professionals.
2. **Recognition accuracy**: AI image recognition is an assistive efficiency tool and may produce errors (especially for loose fresh ingredients and mixed meals). All results support manual correction; 100% accuracy is not promised. All estimated data must be labeled “Estimated.”
3. **Pricing explanation**: Calculations prioritize historical actual purchase prices. Without price history, use reference market prices and label them as estimates.
4. **Capability boundaries**: Heavy computation and AI capabilities are cloud-based; the mini program is only the interaction interface. Export is limited to text / images.
5. **Multi-agent costs**: Genuine multi-agent calls consume more tokens. Manage the impact through streaming, asynchronous processing, and caching. Be prepared to explain costs and optimization strategies during the defense.

---

## 10. Requirements Decision Log (Original Open Questions → Final Answers)

| ID | Topic | Final Decision |
|---|---|---|
| Q1 | Expense-tracking / cost-calculation definitions | Expense tracking = actual payment. Calculations prioritize historical actual purchase prices; otherwise use reference prices labeled as estimates. |
| Q2 | Budget definition | Default to per person; provide a UI switch to a total budget. Avoid complex configuration; decide the demo basis later. |
| Q3 | Constraint hierarchy | Allergens are hard constraints with an absolute veto; taste-based food avoidance is an overridable soft constraint. |
| Q4 | Differentiated meals / labels | Trigger only when needed: no labels without people with specific dietary needs; default to the everyone-compatible plan. |
| Q5 | Pregnancy scenario | Confirmed: AI recommends avoidance where appropriate, both types of dishes coexist, and users choose. |
| Q6 | Multiple agents | Genuine architecture: four agents make independent LLM calls; no simulation. |
| Q7 | Image recognition / LLM | Use DeepSeek multimodal throughout, with dedicated OCR as a fallback option. |
| Q8 | Reference-object estimation | Use the “comparison” method when there is no receipt and no exact information; estimates must be labeled. |
| Q9 | Knowledge base | Architecture first; determine content volume during development. |
| Q10 | Data privacy | Personal twins are owner-only; group-twin visibility is configurable. |
| Q11 | Deliverables | Local demo + demo video + genuinely runnable code. |
| Q12 | Generation mode | Streaming first; if a request times out or the user leaves, complete generation in the background and then notify them. |
| Q13 | Nutrition data | Multiple standards using food composition tables + DRIs, expandable to USDA, with source attribution. |
