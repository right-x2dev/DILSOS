"""CSV order import (validated, all-or-nothing) and run export (CSV / JSON)."""

from __future__ import annotations

import csv
import io
import json
import re
from collections import OrderedDict
from typing import Literal

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, WriterUser
from app.api.errors import ApiError
from app.api.ratelimit import check_rate
from app.api.v1.runs import get_run
from app.api.v1.scenarios import get_scenario
from app.core.config import get_settings
from app.db import models as m
from app.services.audit import audit
from app.services.runs import load_schedule
from app.services.scenario_store import snapshot_from_row
from app.services.snapshot_builder import Clock

router = APIRouter(tags=["import-export"])

REQUIRED = ["order_code", "customer_code", "release_local", "due_local", "priority", "sku_code", "qty"]
HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
CODE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")


class ImportError_(BaseModel):
    row: int
    field: str | None
    message: str


class ImportResult(BaseModel):
    scenario_id: int
    created_orders: list[str]
    lines: int
    errors: list[ImportError_]


def _hhmm(v: str) -> int | None:
    mt = HHMM.match(v.strip())
    if not mt:
        return None
    h, mi = int(mt.group(1)), int(mt.group(2))
    return h * 60 + mi if h <= 47 and mi <= 59 else None


@router.post(
    "/imports/orders",
    response_model=ImportResult,
    status_code=201,
    responses={422: {"description": "validation errors; nothing imported"}},
)
async def import_orders(
    db: DbSession, user: WriterUser, scenario_id: int = Form(...), file: UploadFile = File(...)
) -> ImportResult:
    """CSV columns: order_code, customer_code, release_local (HH:MM), due_local (HH:MM), priority (1-3),
    sku_code, qty. One row per order line (rows sharing order_code form one order). Local times are
    wall-clock times of the scenario's operating day in the facility timezone (>24h = next day)."""
    check_rate(user.id, "import")
    sc = get_scenario(db, scenario_id)
    s = get_settings()
    raw = await file.read(s.max_upload_bytes + 1)
    if len(raw) > s.max_upload_bytes:
        raise ApiError(413, "file_too_large", f"CSV larger than {s.max_upload_bytes} bytes")
    if file.content_type not in (
        None,
        "",
        "text/csv",
        "application/vnd.ms-excel",
        "text/plain",
        "application/octet-stream",
    ):
        raise ApiError(415, "unsupported_media_type", f"expected text/csv, got {file.content_type}")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ApiError(422, "invalid_encoding", "CSV must be UTF-8") from e
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise ApiError(422, "invalid_header", f"missing columns: {', '.join(missing)}", {"required": REQUIRED})
    fac = db.get(m.Facility, sc.facility_id)
    assert fac is not None
    custs = {c.code: c for c in db.scalars(select(m.Customer).where(m.Customer.facility_id == fac.id))}
    skus = {k.code: k for k in db.scalars(select(m.Sku).where(m.Sku.facility_id == fac.id))}
    existing = set(db.scalars(select(m.Order.code).where(m.Order.facility_id == fac.id)))
    errors: list[ImportError_] = []
    orders: OrderedDict[str, dict] = OrderedDict()
    n_lines = 0
    for i, row in enumerate(reader, start=2):
        if i > 5002:
            errors.append(ImportError_(row=i, field=None, message="more than 5000 rows"))
            break
        r = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        code = r["order_code"]
        if not CODE.match(code):
            errors.append(ImportError_(row=i, field="order_code", message="must match [A-Za-z0-9_-]{1,40}"))
            continue
        if code in existing:
            errors.append(ImportError_(row=i, field="order_code", message=f"order {code} already exists"))
            continue
        if r["customer_code"] not in custs:
            errors.append(ImportError_(row=i, field="customer_code", message=f"unknown customer {r['customer_code']}"))
        if r["sku_code"] not in skus:
            errors.append(ImportError_(row=i, field="sku_code", message=f"unknown SKU {r['sku_code']}"))
        rel, due = _hhmm(r["release_local"]), _hhmm(r["due_local"])
        if rel is None:
            errors.append(ImportError_(row=i, field="release_local", message="expected HH:MM"))
        if due is None:
            errors.append(ImportError_(row=i, field="due_local", message="expected HH:MM"))
        if rel is not None and due is not None and due <= rel:
            errors.append(ImportError_(row=i, field="due_local", message="due must be after release"))
        try:
            prio, qty = int(r["priority"]), int(r["qty"])
            if prio not in (1, 2, 3) or not 0 < qty <= 10_000:
                raise ValueError
        except ValueError:
            errors.append(ImportError_(row=i, field="priority/qty", message="priority 1-3, qty 1-10000 integers"))
            continue
        o = orders.setdefault(code, {"customer": r["customer_code"], "rel": rel, "due": due, "prio": prio, "lines": []})
        if (o["customer"], o["rel"], o["due"], o["prio"]) != (r["customer_code"], rel, due, prio):
            errors.append(
                ImportError_(row=i, field="order_code", message="rows of one order disagree on header fields")
            )
        o["lines"].append((r["sku_code"], qty))
        n_lines += 1
    if not orders and not errors:
        errors.append(ImportError_(row=1, field=None, message="no data rows"))
    if errors:
        raise ApiError(
            422,
            "import_validation_failed",
            f"{len(errors)} error(s); nothing was imported",
            [e.model_dump() for e in errors[:200]],
        )
    clk = Clock(fac.timezone, sc.operating_date, sc.horizon_start_local_min)
    for code, o in orders.items():
        row = m.Order(
            facility_id=fac.id,
            code=code,
            customer_id=custs[o["customer"]].id,
            release_at=clk.aware(o["rel"]),
            due_at=clk.aware(o["due"]),
            priority=o["prio"],
            status="OPEN",
            lines=[m.OrderLine(sku_id=skus[sk].id, qty=q) for sk, q in o["lines"]],
        )
        db.add(row)
        db.flush()
        db.add(m.ScenarioOrder(scenario_id=sc.id, order_id=row.id))
    audit(
        db,
        user.id,
        "import",
        "orders",
        str(sc.id),
        detail={"orders": len(orders), "lines": n_lines, "filename": (file.filename or "")[:120]},
    )
    db.commit()
    return ImportResult(scenario_id=sc.id, created_orders=list(orders), lines=n_lines, errors=[])


@router.get("/exports/runs/{run_id}", responses={200: {"content": {"text/csv": {}, "application/json": {}}}})
def export_run(run_id: int, db: DbSession, _: CurrentUser, format: Literal["csv", "json"] = Query("csv")) -> Response:  # noqa: A002
    run = get_run(db, run_id)
    if run.status != "SUCCEEDED":
        raise ApiError(409, "no_schedule", f"run is {run.status}; only validated schedules can be exported")
    snap = snapshot_from_row(db.get(m.ScenarioSnapshotRow, run.snapshot_id))  # type: ignore[arg-type]
    assigns, routes = load_schedule(db, run)
    from datetime import timedelta

    def ts(minute: int | None) -> str:
        return "" if minute is None else (snap.horizon_start + timedelta(minutes=minute)).isoformat()

    if format == "json":
        body = {
            "run_id": run.id,
            "algorithm": run.algorithm,
            "problem_type": run.problem_type,
            "seed": run.seed,
            "schedule_version": run.schedule_version,
            "snapshot_id": run.snapshot_id,
            "horizon_start_utc": snap.horizon_start.isoformat(),
            "timezone": snap.timezone,
            "travel_provenance": snap.travel.provenance,
            "metrics": run.metrics,
            "validation": run.validation,
            "assignments": [a.model_dump() for a in assigns],
            "routes": [r.model_dump() for r in routes],
        }
        return Response(
            json.dumps(body, ensure_ascii=False, indent=1),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="dilsos_run_{run.id}.json"'},
        )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "record",
            "run_id",
            "id",
            "type",
            "orders",
            "resource_or_vehicle",
            "seq_or_dock",
            "start_min",
            "end_min",
            "start_utc",
            "end_utc",
            "extra",
        ]
    )
    for a in assigns:
        w.writerow(
            [
                "task",
                run.id,
                a.task_id,
                a.task_type,
                ";".join(a.order_ids),
                "+".join(a.resources.values()),
                "",
                a.start_min,
                a.end_min,
                ts(a.start_min),
                ts(a.end_min),
                "frozen" if a.frozen else "",
            ]
        )
    for r in routes:
        w.writerow(
            [
                "route",
                run.id,
                f"ROUTE-{r.vehicle_id}",
                "ROUTE",
                ";".join(r.order_ids),
                r.vehicle_id,
                r.dock_id or "",
                r.departure_min,
                r.return_min,
                ts(r.departure_min),
                ts(r.return_min),
                f"distance_m={r.distance_m};load_kg={r.load_kg};geometry={r.geometry}",
            ]
        )
        for st in r.stops:
            w.writerow(
                [
                    "stop",
                    run.id,
                    f"{r.vehicle_id}#{st.seq}",
                    "STOP",
                    ";".join(st.order_ids),
                    r.vehicle_id,
                    st.seq,
                    st.service_start_min,
                    st.service_end_min,
                    ts(st.service_start_min),
                    ts(st.service_end_min),
                    f"customer={st.customer_id};arrival={st.arrival_min};wait={st.wait_min};late={st.late_min}",
                ]
            )
    return Response(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="dilsos_run_{run.id}.csv"'},
    )
