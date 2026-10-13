import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from .domain import validate_plan, snapshot
from .knowledge import retrieve
from .provider import ProviderError
from .schemas import PlanBundle
from .store import packed

log = logging.getLogger(__name__)
ROLES = {
    "inventory": "You are the Inventory Priority Agent. Return JSON {priority_ids:[], allocations:[], warnings:[]}. Prioritize safe inventory that expires soon. Never use spoiled stock or stock after its expiry. You do not change inventory.",
    "health": "You are the Health Adaptation Agent. Return JSON {hard_exclusions:[], nutrition_guidance:[], split_required:false, warnings:[]}. Respect ALL hard allergies and contraindications globally. Special diets and per-diner targets are authoritative. Never diagnose or prescribe medical treatment.",
    "iteration": "You are the Iterative Optimization Agent. Return JSON {preferred_styles:[], feedback_adjustments:[], suggested_order:[]}. Read only the supplied preferences and feedback. Actual recent intake can guide subsequent dishes; never invent memories or override hard constraints.",
    "budget": "You are the Budget Constraint Agent and final plan composer. Build two or three genuinely different variants, including balanced. Use only provided canonical ingredient IDs and prices. Gram quantities are TOTAL raw edible weights per dish, divided equally among suitable_for recipients; [] means everyone. Include every diner each day. Include all ingredients used, including oils. Plain water is allowed without an ingredient entry. Never add unlisted ingredients in preparation steps. All hard exclusions apply to all dishes, including split dishes. Respect meal targets, dates, budget and expiry dates. Explain tradeoffs honestly; no fabricated nutrition or prices.",
}


class Orchestrator:
    def __init__(self, store, provider):
        self.store, self.provider = store, provider
        self.active = None

    def event(self, job, kind, data):
        with self.store.tx() as db:
            self.store.emit(db, job["id"], job["owner_id"], kind, data)

    async def run(self, job):
        s, context = self.store, job["context"]
        async def progress(data):
            self.event(job, "progress", data)
        wiki = retrieve(context["request"]["prompt"])
        async def call(role):
            self.event(job, "stage", {"agent": role, "status": "running"})
            result = await self.provider.complete(role, ROLES[role], {"context": context, "knowledge": wiki}, progress=progress)
            self.event(job, "stage", {"agent": role, "status": "complete"})
            return result
        # Three separate contexts/calls run concurrently; Budget is a fourth independent call.
        results = await asyncio.gather(*(call(role) for role in ("inventory", "health", "iteration")), return_exceptions=True)
        failed = next((r for r in results if isinstance(r, BaseException)), None)
        if failed:
            raise failed
        advice = dict(zip(("inventory", "health", "iteration"), results))
        self.event(job, "stage", {"agent": "budget", "status": "running"})
        schema = PlanBundle.model_json_schema()
        data = {"context": context, "agent_advice": advice, "required_json_schema": schema, "knowledge": wiki}
        raw = await self.provider.complete("budget", ROLES["budget"], data, progress=progress)
        result, errors = validate_plan(raw, context)
        for attempt in range(3):
            if not errors:
                break
            layer = errors[0]["layer"]
            role = {"health": "health", "inventory": "inventory"}.get(layer, "budget")
            self.event(job, "validation", {"attempt": attempt+1, "errors": errors[:12], "repair_agent": role})
            raw = await self.provider.complete(role,
                ROLES[role] + "\nRepair the ENTIRE plan, returning the PlanBundle JSON schema (not your usual advice schema). " + ROLES["budget"],
                {**data, "previous_plan": raw, "validation_errors": errors[:40]}, progress=progress)
            result, errors = validate_plan(raw, context)
        if errors:
            with s.tx() as db:
                current = s.get(db, job["id"], "job")
                current.update(status="needs_input", errors=errors[:40], message="No unvalidated plan was published. Adjust prices, stock, targets or soft constraints and create a new request. Hard exclusions cannot be relaxed.")
                s.put(db, "job", job["group_id"], job["owner_id"], current, job["id"])
                s.emit(db, job["id"], job["owner_id"], "needs_input", {"errors": errors[:40], "message": current["message"]})
                self.notify(db, job, "Plan needs your input")
            return
        # A long-running model call may outlive a profile, stock or price edit.
        with s.tx() as db:
            current_context = snapshot(s, db, job["group_id"], job["owner_id"], context["request"])
        if packed(current_context) != packed(context):
            raise ProviderError("Planning inputs changed during generation. Start a fresh plan; no stale recommendation was published.")
        # Only validated days are streamed to the UI.
        for variant in result["variants"]:
            for day in variant["days"]:
                self.event(job, "day", {"mode": variant["mode"], "day": day})
        with s.tx() as db:
            current = s.get(db, job["id"], "job")
            current.update(status="complete", result=result, agents=list(ROLES), message="Validated plan ready")
            s.put(db, "job", job["group_id"], job["owner_id"], current, job["id"])
            s.emit(db, job["id"], job["owner_id"], "complete", {"job_id": job["id"]})
            self.notify(db, job, "Your weekly meal plan is ready")

    def notify(self, db, job, text):
        self.store.put(db, "notification", job["group_id"], job["owner_id"],
                       {"text": text, "job_id": job["id"], "read": False})
        self.store.emit(db, job["group_id"], job["owner_id"], "plans_changed", {})

    def recover(self):
        # Interrupted calls may have been charged: require explicit retry rather than silently billing again.
        with self.store.tx() as db:
            for job in self.store.items(db, "job"):
                if job["status"] == "running":
                    job.update(status="failed", message="Server restarted during generation. Please start a new request.")
                    self.store.put(db, "job", job["group_id"], job["owner_id"], job, job["id"])
                    self.store.emit(db, job["id"], job["owner_id"], "failed", {"message": job["message"]})
                    self.notify(db, job, job["message"])

    async def worker(self):
        while True:
            job = None
            with self.store.tx() as db:
                queued = [j for j in self.store.items(db, "job") if j["status"] == "queued"]
                if queued:
                    job = queued[-1]
                    job["status"] = "running"
                    self.store.put(db, "job", job["group_id"], job["owner_id"], job, job["id"])
            if job:
                try:
                    self.active = job["id"]
                    await self.run(job)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    message = str(exc) if isinstance(exc, ProviderError) else "Generation failed; inspect server logs and retry."
                    if not isinstance(exc, ProviderError):
                        log.exception("Planning job failed: %s", job["id"])
                    with self.store.tx() as db:
                        current = self.store.get(db, job["id"], "job")
                        current.update(status="failed", message=message)
                        self.store.put(db, "job", job["group_id"], job["owner_id"], current, job["id"])
                        self.store.emit(db, job["id"], job["owner_id"], "failed", {"message": message})
                        self.notify(db, job, message)
                finally:
                    self.active = None
            else:
                await asyncio.sleep(.3)
