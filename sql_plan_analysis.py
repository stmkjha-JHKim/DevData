"""sql_plan_analysis.py -- rule-based execution-plan analyzer for the SQL
detail modal's "Execution Plan Analysis" section (opened from any SQL_ID
link across the app: Ops tab's Top SQL cards, Tuning tab's Slow SQL,
Recovery's Recent DML, the session list's "View Running Query").

Deliberately license-free and read-only, same reasoning as tuning.py: the
plan tree comes straight from V$SQL_PLAN (an ordinary V$ view already
populated for any cursor still in the shared pool), not from re-executing
EXPLAIN PLAN or calling the DBMS_XPLAN package -- so this needs no extra
privilege beyond SELECT on V$SQL_PLAN, and never re-runs the SQL itself.

Like tuning.py, findings are returned as structured data (rule id +
severity + numeric values), not pre-rendered text -- the frontend's i18n
layer turns each one into a localized title/message.
"""

from typing import Optional

# Thresholds are deliberately simple, single-cut-off rules (no history/
# baseline needed, unlike tuning.py's rate-based checks) since a plan is a
# snapshot of one cursor, not a trend.
FULL_SCAN_CRITICAL_ROWS = 1_000_000
FULL_SCAN_WARNING_ROWS = 50_000
NESTED_LOOP_WARNING_ROWS = 100_000
LARGE_SORT_WARNING_BYTES = 10 * 1024 * 1024  # 10 MB
TOP_COST_STEP_MIN_SHARE = 0.5  # a single step must own >=50% of total cost to be called out


def _num(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _plan_row(r: dict) -> dict:
    return {
        "id": r.get("ID"),
        "operation": r.get("OPERATION"),
        "options": r.get("OPTIONS"),
        "objectOwner": r.get("OBJECT_OWNER"),
        "objectName": r.get("OBJECT_NAME"),
        "objectType": r.get("OBJECT_TYPE"),
        "cardinality": _num(r.get("CARDINALITY")),
        "bytes": _num(r.get("BYTES")),
        "cost": _num(r.get("COST")),
    }


def analyze_plan(plan_rows: list) -> list:
    """plan_rows: list of dicts straight from a V$SQL_PLAN query (upper-case
    column-name keys, one row per plan step, ordered by ID). Returns a list
    of findings sorted worst-severity-first, same shape/convention as
    tuning.py's `findings`."""
    findings = []

    full_scans = []
    cartesians = []
    nested_loops = []
    large_sorts = []

    for r in plan_rows:
        operation = (r.get("OPERATION") or "").upper()
        options = (r.get("OPTIONS") or "").upper()
        cardinality = _num(r.get("CARDINALITY"))
        byte_size = _num(r.get("BYTES"))

        if operation == "TABLE ACCESS" and options == "FULL":
            if cardinality is not None and cardinality >= FULL_SCAN_WARNING_ROWS:
                sev = "critical" if cardinality >= FULL_SCAN_CRITICAL_ROWS else "warning"
                full_scans.append({**_plan_row(r), "severity": sev})

        if options == "CARTESIAN":
            cartesians.append(_plan_row(r))

        if operation == "NESTED LOOPS" and options != "CARTESIAN":
            if cardinality is not None and cardinality >= NESTED_LOOP_WARNING_ROWS:
                nested_loops.append({**_plan_row(r), "severity": "warning"})

        if operation == "SORT" and options in ("ORDER BY", "GROUP BY", "UNIQUE", "AGGREGATE"):
            if byte_size is not None and byte_size >= LARGE_SORT_WARNING_BYTES:
                large_sorts.append({**_plan_row(r), "severity": "warning"})

    if full_scans:
        worst = "critical" if any(row["severity"] == "critical" for row in full_scans) else "warning"
        findings.append({"ruleId": "plan_full_table_scan", "severity": worst, "rows": full_scans})

    if cartesians:
        findings.append({"ruleId": "plan_cartesian_join", "severity": "critical", "rows": cartesians})

    if nested_loops:
        findings.append({"ruleId": "plan_nested_loop_large", "severity": "warning", "rows": nested_loops})

    if large_sorts:
        findings.append({"ruleId": "plan_large_sort", "severity": "warning", "rows": large_sorts})

    # Highest single-step cost relative to the plan's total (root, id=0)
    # cost, if any one step dominates -- points the reader at where to
    # focus rather than leaving them to scan the whole tree.
    root = next((r for r in plan_rows if r.get("PARENT_ID") is None), None)
    total_cost = _num(root.get("COST")) if root else None
    if total_cost and total_cost > 0:
        non_root = [r for r in plan_rows if r.get("PARENT_ID") is not None and _num(r.get("COST")) is not None]
        if non_root:
            top = max(non_root, key=lambda r: _num(r.get("COST")))
            top_cost = _num(top.get("COST"))
            share = top_cost / total_cost if top_cost is not None else 0
            if share >= TOP_COST_STEP_MIN_SHARE:
                findings.append({
                    "ruleId": "plan_top_cost_step",
                    "severity": "info",
                    "step": {**_plan_row(top), "costPct": round(share * 100, 1)},
                })

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: severity_order.get(f["severity"], 3))
    return findings
