"""Scenarios: list / build (synthetic generator) / update (optimistic concurrency) / clone / validate / geo."""

from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm.exc import StaleDataError

from app.api.deps import CurrentUser, DbSession, WriterUser
from app.api.errors import ApiError
from app.db import models as m
from app.optimization.common.contracts import ObjectiveWeights, ScenarioParams
from app.schemas.api import (
    CloneRequest,
    FacilityOut,
    GeoOut,
    GeoPoint,
    InputValidation,
    Page,
    ScenarioOut,
    ScenarioUpdate,
    SyntheticScenarioCreate,
)
from app.seed.generator import GeneratorConfig, generate
from app.services.audit import audit
from app.services.input_validation import validate_inputs
from app.services.scenario_store import (
    current_snapshot,
    persist_definition,
    snapshot_count,
    snapshot_from_row,
)
from app.services.snapshot_builder import Clock

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


def get_scenario(db, sid: int) -> m.Scenario:  # type: ignore[no-untyped-def]
    sc = db.get(m.Scenario, sid)
    if sc is None:
        raise ApiError(404, "not_found", f"scenario {sid} not found")
    return sc


def scenario_out(db, sc: m.Scenario) -> ScenarioOut:  # type: ignore[no-untyped-def]
    fac = db.get(m.Facility, sc.facility_id)
    n_orders = db.scalar(select(func.count()).select_from(m.ScenarioOrder).where(m.ScenarioOrder.scenario_id == sc.id))

    def cnt(model) -> int:  # type: ignore[no-untyped-def]
        return int(db.scalar(select(func.count()).select_from(model).where(model.facility_id == sc.facility_id)) or 0)

    hs = Clock(fac.timezone, sc.operating_date, sc.horizon_start_local_min).horizon_start.astimezone(UTC)
    return ScenarioOut(
        id=sc.id,
        name=sc.name,
        description=sc.description,
        facility=FacilityOut(id=fac.id, code=fac.code, name=fac.name, timezone=fac.timezone),
        operating_date=sc.operating_date,
        horizon_start=hs,
        horizon_min=sc.horizon_min,
        seed=sc.seed,
        status=sc.status,
        version=sc.version,
        parent_scenario_id=sc.parent_scenario_id,
        order_count=n_orders or 0,
        created_at=sc.created_at,
        params=ScenarioParams(**sc.params),
        weights=ObjectiveWeights(**sc.weights),
        task_model=sc.task_model,
        travel_params=sc.travel_params,
        resource_counts={
            "workers": cnt(m.Worker),
            "pack_stations": cnt(m.PackStation),
            "docks": cnt(m.Dock),
            "vehicles": cnt(m.Vehicle),
            "equipment": cnt(m.Equipment),
        },
        snapshot_versions=snapshot_count(db, sc.id),
    )


@router.get("", response_model=Page[ScenarioOut])
def list_scenarios(
    db: DbSession, _: CurrentUser, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)
) -> Page[ScenarioOut]:
    total = db.scalar(select(func.count()).select_from(m.Scenario)) or 0
    rows = db.scalars(select(m.Scenario).order_by(m.Scenario.id).limit(limit).offset(offset))
    return Page(items=[scenario_out(db, s) for s in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=ScenarioOut, status_code=201)
def create_scenario(body: SyntheticScenarioCreate, db: DbSession, user: WriterUser) -> ScenarioOut:
    n = (db.scalar(select(func.count()).select_from(m.Facility)) or 0) + 1
    cfg = GeneratorConfig(
        name=body.name,
        description=body.description or "시나리오 빌더에서 생성한 합성 시나리오",
        facility_code=f"DC-U{n:03d}",
        seed=body.seed,
        operating_date=body.operating_date,
        n_orders=body.n_orders,
        n_workers=body.n_workers,
        n_pack_stations=body.n_pack_stations,
        n_docks=body.n_docks,
        n_vans=body.n_vans,
        n_trucks=body.n_trucks,
        area_km=body.area_km,
        deadline_tightness=body.deadline_tightness,
        inventory_shortage_skus=body.inventory_shortage_skus,
        time_window_mode=body.time_window_mode,
    )
    d = generate(cfg)
    d = d.model_copy(update={"weights": body.weights})
    sc = persist_definition(db, d, user.id)
    audit(db, user.id, "create", "scenario", str(sc.id), detail={"generator": cfg.model_dump(mode="json")})
    db.commit()
    return scenario_out(db, sc)


@router.get("/{scenario_id}", response_model=ScenarioOut)
def get_one(scenario_id: int, db: DbSession, _: CurrentUser) -> ScenarioOut:
    return scenario_out(db, get_scenario(db, scenario_id))


@router.patch("/{scenario_id}", response_model=ScenarioOut)
def update_scenario(scenario_id: int, body: ScenarioUpdate, db: DbSession, user: WriterUser) -> ScenarioOut:
    sc = get_scenario(db, scenario_id)
    if sc.version != body.version:
        raise ApiError(
            409,
            "version_conflict",
            "scenario was modified by someone else; reload and retry",
            {"current_version": sc.version},
        )
    before = sc.version
    for field in ("name", "description", "seed", "horizon_min"):
        v = getattr(body, field)
        if v is not None:
            setattr(sc, field, v)
    if body.params is not None:
        sc.params = body.params.model_dump()
    if body.weights is not None:
        sc.weights = body.weights.model_dump()
    try:
        db.flush()
    except StaleDataError as e:
        db.rollback()
        raise ApiError(409, "version_conflict", "concurrent update detected") from e
    audit(db, user.id, "update", "scenario", str(sc.id), before_ref=f"v{before}", after_ref=f"v{sc.version}")
    db.commit()
    return scenario_out(db, sc)


@router.post("/{scenario_id}/clone", response_model=ScenarioOut, status_code=201)
def clone(scenario_id: int, body: CloneRequest, db: DbSession, user: WriterUser) -> ScenarioOut:
    src = get_scenario(db, scenario_id)
    sc = m.Scenario(
        facility_id=src.facility_id,
        name=body.name,
        description=f"clone of #{src.id}: {src.description}"[:500],
        operating_date=src.operating_date,
        horizon_start_local_min=src.horizon_start_local_min,
        horizon_min=src.horizon_min,
        seed=src.seed,
        params=dict(src.params),
        weights=dict(src.weights),
        task_model=dict(src.task_model),
        travel_params=dict(src.travel_params),
        status="READY",
        parent_scenario_id=src.id,
        created_by=user.id,
    )
    db.add(sc)
    db.flush()
    for so in db.scalars(select(m.ScenarioOrder).where(m.ScenarioOrder.scenario_id == src.id)):
        db.add(m.ScenarioOrder(scenario_id=sc.id, order_id=so.order_id))
    audit(db, user.id, "clone", "scenario", str(sc.id), before_ref=f"scenario:{src.id}")
    db.commit()
    return scenario_out(db, sc)


@router.post("/{scenario_id}/validate", response_model=InputValidation)
def validate(scenario_id: int, db: DbSession, _: CurrentUser) -> InputValidation:
    sc = get_scenario(db, scenario_id)
    row = current_snapshot(db, sc, reason="validate")
    db.commit()
    out = validate_inputs(snapshot_from_row(row))
    out.summary["snapshot_id"] = row.id
    out.summary["snapshot_version"] = row.version
    out.summary["content_hash"] = row.content_hash
    return out


@router.get("/{scenario_id}/geo", response_model=GeoOut)
def geo(scenario_id: int, db: DbSession, _: CurrentUser) -> GeoOut:
    sc = get_scenario(db, scenario_id)
    row = current_snapshot(db, sc, reason="geo")
    db.commit()
    snap = snapshot_from_row(row)
    fac = db.get(m.Facility, sc.facility_id)
    locs = {loc.id: loc for loc in snap.locations}
    dep = locs[snap.depot_location_id]
    pts = [
        GeoPoint(
            id="DEPOT",
            kind="depot",
            name=fac.name if fac else "DC",
            x_km=dep.x_km,
            y_km=dep.y_km,
            lat=dep.lat,
            lon=dep.lon,
        )
    ]
    for c in snap.customers:
        loc = locs[c.location_id]
        pts.append(
            GeoPoint(
                id=c.id,
                kind="customer",
                name=c.name,
                x_km=loc.x_km,
                y_km=loc.y_km,
                lat=loc.lat,
                lon=loc.lon,
                tw_start=c.tw_start,
                tw_end=c.tw_end,
            )
        )
    return GeoOut(
        coordinate_provenance="synthetic (generated km offsets; lat/lon derived for display only)",
        travel_provenance=snap.travel.provenance,
        travel_notes=snap.travel.notes,
        points=pts,
    )
