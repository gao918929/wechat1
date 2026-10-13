# 蔬菜菌菇 Vegetables & Mushrooms

营养数值：每 100 g 可食部（近似值，参照《中国食物成分表》第6版）。价格：元/kg（城市商超常见区间）。
`shelf` 为保质期类别（见 `03_rules/shelf_life.md`），`shelf_days` 非 `-` 时覆盖类别默认天数。
`piece_g` / `piece_cm` 为单个（棵/根/个）参考重量与主尺寸，用于参照物估算。

| name | en | aliases | section | shelf | shelf_days | kcal | protein | fat | carb | fiber | vc | ca | fe | na | price_min | price_max | piece_g | piece_cm | allergens | tags |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 番茄 | tomato | 西红柿/圣女果 | vegetables | fruit_veg | - | 15 | 0.9 | 0.2 | 4.0 | 0.5 | 19 | 10 | 0.4 | 5 | 6 | 10 | 150 | 7 | - | low_gi/vegetable |
| 黄瓜 | cucumber | 青瓜 | vegetables | fruit_veg | - | 16 | 0.8 | 0.2 | 2.9 | 0.5 | 9 | 24 | 0.5 | 5 | 4 | 8 | 200 | 25 | - | low_gi/vegetable |
| 大白菜 | chinese cabbage | 白菜/黄芽白 | vegetables | leafy | 10 | 20 | 1.5 | 0.1 | 3.2 | 0.8 | 31 | 50 | 0.7 | 58 | 2 | 4 | 2000 | 20 | - | vegetable/budget |
| 娃娃菜 | baby cabbage | - | vegetables | leafy | 7 | 13 | 1.9 | 0.3 | 2.4 | 0.6 | 12 | 78 | 0.4 | 40 | 6 | 10 | 250 | 15 | - | vegetable |
| 小白菜 | bok choy | 青菜/上海青/油菜 | vegetables | leafy | - | 15 | 1.5 | 0.3 | 2.7 | 1.1 | 28 | 90 | 1.9 | 74 | 4 | 8 | 50 | 15 | - | vegetable/leafy_green |
| 菠菜 | spinach | 菠菱菜 | vegetables | leafy | - | 28 | 2.6 | 0.3 | 4.5 | 1.7 | 32 | 66 | 2.9 | 85 | 6 | 12 | 40 | 25 | - | vegetable/leafy_green/iron |
| 生菜 | lettuce | 球生菜/罗马生菜 | vegetables | leafy | - | 15 | 1.3 | 0.3 | 2.0 | 0.7 | 13 | 34 | 0.9 | 33 | 6 | 10 | 300 | 15 | - | vegetable/leafy_green/raw_ok |
| 西兰花 | broccoli | 西蓝花/青花菜 | vegetables | fruit_veg | 5 | 36 | 4.1 | 0.6 | 4.3 | 1.6 | 51 | 67 | 1.0 | 19 | 8 | 14 | 400 | 15 | - | vegetable/high_fiber |
| 胡萝卜 | carrot | 红萝卜 | vegetables | root | - | 39 | 1.0 | 0.2 | 8.8 | 1.1 | 13 | 32 | 1.0 | 71 | 3 | 6 | 150 | 18 | - | vegetable/vitamin_a |
| 土豆 | potato | 马铃薯/洋芋 | vegetables | root | - | 77 | 2.6 | 0.2 | 17.8 | 1.1 | 14 | 7 | 0.4 | 6 | 3 | 5 | 200 | 9 | - | starchy_vegetable/budget |
| 洋葱 | onion | 圆葱 | vegetables | root | - | 40 | 1.1 | 0.2 | 9.0 | 0.9 | 8 | 24 | 0.6 | 4 | 3 | 6 | 200 | 8 | - | vegetable |
| 青椒 | green pepper | 甜椒/菜椒/彩椒 | vegetables | fruit_veg | - | 22 | 1.0 | 0.2 | 5.4 | 1.4 | 72 | 14 | 0.8 | 3 | 6 | 10 | 100 | 9 | - | vegetable |
| 茄子 | eggplant | 紫茄子 | vegetables | fruit_veg | - | 23 | 1.1 | 0.2 | 4.9 | 1.3 | 5 | 24 | 0.5 | 5 | 5 | 9 | 250 | 25 | - | vegetable |
| 冬瓜 | wax gourd | - | vegetables | fruit_veg | 14 | 12 | 0.4 | 0.2 | 2.6 | 0.7 | 18 | 19 | 0.2 | 2 | 2 | 4 | 1000 | 25 | - | vegetable/budget/low_gi |
| 豆芽 | bean sprouts | 绿豆芽/黄豆芽 | vegetables | leafy | 2 | 18 | 2.1 | 0.1 | 2.9 | 0.8 | 6 | 9 | 0.6 | 4 | 3 | 6 | - | - | - | vegetable/budget |
| 芹菜 | celery | 西芹 | vegetables | leafy | 7 | 22 | 1.2 | 0.2 | 4.5 | 1.2 | 8 | 80 | 1.2 | 159 | 4 | 8 | 500 | 40 | - | vegetable/high_fiber |
| 香菜 | cilantro | 芫荽 | vegetables | leafy | - | 33 | 1.8 | 0.4 | 6.2 | 1.2 | 48 | 101 | 2.9 | 49 | 15 | 30 | 20 | 20 | - | herb/cilantro |
| 南瓜 | pumpkin | 倭瓜 | vegetables | root | 30 | 23 | 0.7 | 0.1 | 5.3 | 0.8 | 8 | 16 | 0.4 | 1 | 2 | 4 | 1500 | 20 | - | starchy_vegetable/budget/stomach_friendly |
| 山药 | chinese yam | 铁棍山药/淮山 | vegetables | root | - | 57 | 1.9 | 0.2 | 12.4 | 0.8 | 5 | 16 | 0.3 | 19 | 8 | 14 | 400 | 40 | - | starchy_vegetable/stomach_friendly |
| 莲藕 | lotus root | 藕 | vegetables | root | - | 47 | 1.2 | 0.2 | 11.5 | 2.2 | 19 | 18 | 0.3 | 34 | 8 | 12 | 400 | 20 | - | starchy_vegetable |
| 玉米 | sweet corn | 甜玉米/鲜玉米 | vegetables | fruit_veg | 5 | 112 | 4.0 | 1.2 | 22.8 | 2.9 | 16 | 1 | 1.1 | 1 | 4 | 8 | 250 | 20 | - | whole_grain/starchy_vegetable |
| 香菇 | shiitake | 鲜香菇/冬菇 | vegetables | mushroom | - | 26 | 2.2 | 0.3 | 5.2 | 3.3 | 1 | 2 | 0.3 | 1 | 12 | 20 | 20 | 5 | - | mushroom/umami |
| 金针菇 | enoki mushroom | - | vegetables | mushroom | - | 32 | 2.4 | 0.4 | 6.0 | 2.7 | 2 | 1 | 1.4 | 4 | 8 | 14 | 150 | 15 | - | mushroom |
| 木耳 | dried wood ear | 黑木耳/干木耳 | staples | dry | - | 265 | 12.1 | 1.5 | 65.6 | 29.9 | 0 | 247 | 97.4 | 49 | 60 | 100 | - | - | - | mushroom/high_fiber/iron |
| 大蒜 | garlic | 蒜/蒜头/蒜瓣 | seasonings | root | 60 | 128 | 4.5 | 0.2 | 27.6 | 1.1 | 7 | 39 | 1.2 | 20 | 8 | 14 | 40 | 5 | - | aromatic |
| 姜 | ginger | 生姜/老姜 | seasonings | root | 30 | 46 | 1.3 | 0.6 | 10.3 | 2.7 | 4 | 27 | 1.4 | 15 | 10 | 16 | 100 | 10 | - | aromatic |
| 葱 | scallion | 小葱/大葱/葱花/香葱 | seasonings | leafy | 7 | 30 | 1.7 | 0.3 | 6.5 | 1.3 | 17 | 29 | 0.7 | 5 | 6 | 10 | 20 | 30 | - | aromatic |
