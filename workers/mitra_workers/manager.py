"""Per-app manager: a review of how one app has been running, from measured numbers.

No model is involved. Errors, slow or over-budget model runs, evictions, missing runtimes and
unresolved connectors are facts in the memory log and the governor's status; reading them
needs arithmetic, not a language model, and costs no RAM.
"""
from . import memory, models


def review(app) -> dict:
    pub = app.public()
    stats = memory.app_stats(app.id, 7)
    status = models.governor_status()
    budget = (status.get("limits") or {}).get("model_budget_mb", 500)
    findings = []

    for n in pub["needs"]:
        if not n["ready"]:
            findings.append({"level": "warn", "text": f"{n['capability']} is not ready: {n.get('hint')}"})
    for c in pub["connectors"]:
        if not c["available"]:
            findings.append({"level": "warn", "text": f"Connector {c['type']}:{c.get('path', '')} does not resolve to a folder yet."})
    if stats["errors"]:
        findings.append({"level": "bad", "text": f"{sum(stats['errors'].values())} errors in 7 days. Most common: {next(iter(stats['errors']))}"})
    for name, mc in stats["model_calls"].items():
        if mc.get("over"):
            findings.append({"level": "bad", "text": f"{name} went over its own RAM cap on {mc['over']} of {mc['n']} runs (peak {mc['peak_mb']} MB)."})
        if mc["n"] >= 3 and mc["avg_ms"] > 20000:
            findings.append({"level": "warn", "text": f"{name} averages {mc['avg_ms'] // 1000} s per run. A lighter candidate would respond faster."})
    if stats["evictions"]:
        findings.append({"level": "bad", "text": f"The governor stopped this app's models {stats['evictions']} times."})
    if stats["denied"]:
        findings.append({"level": "warn", "text": f"{stats['denied']} model loads were refused for lack of free RAM or because another model was running."})
    held = [l for l in status.get("leases", []) if app.id in (l.get("apps") or [])]
    if not findings:
        findings.append({"level": "ok", "text": "Nothing to flag: no errors, no evictions, every model run inside budget."})
    memory.log(app.id, "manager.review", {"findings": [f["text"] for f in findings]})
    return {"app": app.id, "stats": stats, "findings": findings, "held": held, "budget_mb": budget}
