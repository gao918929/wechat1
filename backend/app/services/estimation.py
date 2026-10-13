"""Reference-object ratio estimation engine (the "comparison" method)."""
from __future__ import annotations

from ..wiki import Wiki

DEFAULT_RANGE = 0.15
LOW_CONFIDENCE_RANGE = 0.25


def calibration_factor(twin_data: dict | None, name: str) -> float:
    cal = ((twin_data or {}).get("calibration") or {}).get(name)
    if not cal:
        return 1.0
    return max(0.5, min(2.0, float(cal.get("factor", 1.0))))


def estimate_weight(item: dict, wiki: Wiki, reference: dict | None = None, twin_data: dict | None = None) -> dict:
    """Estimate an item's weight.

    ``item``: {name, count, size_px, confidence, weight_g?} from the vision model.
    ``reference``: {key|name, size_px, size_cm?} for the reference object in the same photo.
    Exact values (receipt / user input) always win, so only call this when ``weight_g`` is missing.
    Returns {weight_g, range_pct, estimated, method, text} or a "needs weight" fallback.
    """
    ing = wiki.ingredient(item.get("name", ""))
    count = item.get("count") or 1
    conf = item.get("confidence", 0.8)
    rng = DEFAULT_RANGE if conf >= 0.6 else LOW_CONFIDENCE_RANGE
    name = ing.name if ing else item.get("name", "")
    factor = calibration_factor(twin_data, name)

    weight = None
    method = ""
    ref_cm = None
    if reference and reference.get("size_px"):
        ref_obj = wiki.reference_objects.get(reference.get("key", "")) or next(
            (r for r in wiki.reference_objects.values() if r.name == reference.get("name")), None)
        ref_cm = reference.get("size_cm") or (ref_obj.size_cm if ref_obj else None)
    if ing and ing.piece_g and ing.piece_cm and ref_cm and item.get("size_px"):
        size_cm = item["size_px"] / reference["size_px"] * ref_cm
        weight = ing.piece_g * (size_cm / ing.piece_cm) ** 3 * count
        method = f"参照物对比：约 {size_cm:.1f} cm（参照物 {ref_cm:g} cm）"
    elif ing and ing.piece_g:
        weight = ing.piece_g * count
        method = f"按单个参考重量 {ing.piece_g:g} g × {count:g}"
        rng = max(rng, LOW_CONFIDENCE_RANGE)

    if weight is None:
        return {"weight_g": None, "estimated": True, "range_pct": None, "method": "",
                "text": "已识别食材，需补充重量"}
    weight *= factor
    if factor != 1.0:
        method += f"；按历史修正校准 ×{factor:.2f}"
    weight = round(weight / 10) * 10 if weight >= 100 else round(weight)
    return {"weight_g": weight, "estimated": True, "range_pct": round(rng * 100), "method": method,
            "text": f"约 {weight:g} g ±{rng:.0%}（估算）"}


def update_calibration(twin_data: dict, name: str, estimated_g: float, actual_g: float) -> dict:
    """Record a user correction so future estimates for this ingredient are calibrated."""
    if not estimated_g or not actual_g:
        return twin_data
    cal = twin_data.setdefault("calibration", {})
    cur = cal.get(name, {"factor": 1.0, "n": 0})
    ratio = actual_g / estimated_g
    n = cur["n"] + 1
    cur = {"factor": round((cur["factor"] * cur["n"] + ratio * cur["factor"]) / n, 3) if cur["n"] else round(ratio, 3),
           "n": n}
    cal[name] = cur
    return twin_data
