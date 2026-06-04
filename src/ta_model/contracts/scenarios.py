"""Synthetic simulator scenario-suite contracts.

Traceability:
- FR-012: deterministic replay evidence for historical simulator behavior.
- RISK-001: crash scenario labels market drawdown stress evidence.
- RISK-002: liquidity/outage scenarios label liquidity-collapse and fail-closed evidence.

Scope: fake/local QA scenarios only; no real data source, paper gateway, live
capital, leverage, derivatives, margin, shorting, market making, HFT, or model
promotion path is introduced.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from ta_model.contracts.instrument_master import CanonicalId, ContractModel, NonEmptyString
from ta_model.contracts.simulation import ReplayFillStatus, ReplayRejectReason, ReplayReport


class SyntheticScenarioId(StrEnum):
    """Required S6-004 deterministic fake-asset scenario identifiers."""

    RANDOM_WALK = "random_walk"
    TREND = "trend"
    CRASH = "crash"
    SPREAD = "spread"
    LIQUIDITY = "liquidity"
    OUTAGE = "outage"


class ScenarioStatusCount(ContractModel):
    """Per-status replay accounting for one synthetic scenario."""

    status: ReplayFillStatus
    count: int = Field(gt=0)


class SyntheticScenarioResult(ContractModel):
    """Deterministic per-scenario evidence from the integrated replay path."""

    scenario_id: SyntheticScenarioId
    scenario_name: NonEmptyString
    traceability: tuple[NonEmptyString, ...]
    stress_labels: tuple[NonEmptyString, ...] = ()
    replay_report_id: CanonicalId
    replay_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    market_data_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status_counts: tuple[ScenarioStatusCount, ...]
    rejection_counts: tuple[tuple[ReplayRejectReason, int], ...] = ()
    total_cost: Decimal = Field(ge=Decimal("0"))
    filled_quantity: Decimal = Field(ge=Decimal("0"))
    remaining_quantity: Decimal = Field(ge=Decimal("0"))
    min_close_price: Decimal = Field(ge=Decimal("0"))
    max_close_price: Decimal = Field(ge=Decimal("0"))
    final_balances: tuple[tuple[CanonicalId, Decimal], ...] = ()
    comparison_total_cost: Decimal | None = Field(default=None, ge=Decimal("0"))

    @model_validator(mode="after")
    def traceability_matches_required_scenario_evidence(self) -> SyntheticScenarioResult:
        _validate_result_traceability(self)
        return self

    @classmethod
    def from_replay_report(
        cls,
        *,
        scenario_id: SyntheticScenarioId,
        scenario_name: str,
        traceability: tuple[str, ...],
        stress_labels: tuple[str, ...],
        report: ReplayReport,
        min_close_price: Decimal,
        max_close_price: Decimal,
        comparison_total_cost: Decimal | None = None,
    ) -> SyntheticScenarioResult:
        status_totals: dict[ReplayFillStatus, int] = {}
        for result in report.results:
            status_totals[result.status] = status_totals.get(result.status, 0) + 1
        final_balances: tuple[tuple[str, Decimal], ...] = ()
        if report.final_account_state is not None:
            final_balances = tuple(
                (balance.asset_id, balance.available)
                for balance in sorted(
                    report.final_account_state.balances,
                    key=lambda item: (item.venue_id, item.asset_id),
                )
            )
        return cls(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            traceability=traceability,
            stress_labels=stress_labels,
            replay_report_id=report.replay_report_id,
            replay_report_hash=report.replay_report_hash,
            market_data_hash=report.market_data_hash,
            status_counts=tuple(
                ScenarioStatusCount(status=status, count=status_totals[status])
                for status in sorted(status_totals, key=lambda item: item.value)
            ),
            rejection_counts=tuple((item.reason, item.count) for item in report.rejection_counts),
            total_cost=sum((result.total_cost for result in report.results), Decimal("0")),
            filled_quantity=sum(
                (result.filled_quantity for result in report.results), Decimal("0")
            ),
            remaining_quantity=sum(
                (result.remaining_quantity for result in report.results), Decimal("0")
            ),
            min_close_price=min_close_price,
            max_close_price=max_close_price,
            final_balances=final_balances,
            comparison_total_cost=comparison_total_cost,
        )


class SyntheticScenarioSuiteReport(ContractModel):
    """Deterministic S6-004 synthetic scenario-suite evidence artifact."""

    suite_report_id: CanonicalId
    suite_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    run_id: CanonicalId
    seed: int
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-012",)
    risk_ids: tuple[NonEmptyString, ...] = ("RISK-001", "RISK-002", "RISK-005")
    scenario_results: tuple[SyntheticScenarioResult, ...]

    @model_validator(mode="after")
    def suite_identity_is_deterministic(self) -> SyntheticScenarioSuiteReport:
        _validate_required_scenarios(self.scenario_results)
        for result in self.scenario_results:
            _validate_result_traceability(result)
        expected_hash = build_synthetic_scenario_suite_hash(
            run_id=self.run_id,
            seed=self.seed,
            requirement_ids=self.requirement_ids,
            risk_ids=self.risk_ids,
            scenario_results=self.scenario_results,
        )
        if self.suite_hash != expected_hash:
            raise ValueError("suite_hash is not deterministic")
        if self.suite_report_id != build_synthetic_scenario_suite_id(suite_hash=self.suite_hash):
            raise ValueError("suite_report_id is not deterministic")
        return self


def make_synthetic_scenario_suite_report(
    *, run_id: str, seed: int, scenario_results: tuple[SyntheticScenarioResult, ...]
) -> SyntheticScenarioSuiteReport:
    """Build a suite report with deterministic hash/id from replay evidence."""

    suite_hash = build_synthetic_scenario_suite_hash(
        run_id=run_id,
        seed=seed,
        requirement_ids=("FR-012",),
        risk_ids=("RISK-001", "RISK-002", "RISK-005"),
        scenario_results=scenario_results,
    )
    return SyntheticScenarioSuiteReport(
        suite_report_id=build_synthetic_scenario_suite_id(suite_hash=suite_hash),
        suite_hash=suite_hash,
        run_id=run_id,
        seed=seed,
        scenario_results=scenario_results,
    )


def build_synthetic_scenario_suite_hash(
    *,
    run_id: str,
    seed: int,
    requirement_ids: tuple[str, ...],
    risk_ids: tuple[str, ...],
    scenario_results: tuple[SyntheticScenarioResult, ...],
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "requirement_ids": requirement_ids,
                "risk_ids": risk_ids,
                "run_id": run_id,
                "scenario_results": tuple(
                    json.loads(result.model_dump_json()) for result in scenario_results
                ),
                "seed": seed,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def build_synthetic_scenario_suite_id(*, suite_hash: str) -> str:
    digest = hashlib.sha256(
        json.dumps({"suite_hash": suite_hash}, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()[:32]
    return f"SYNTHSUITE:{digest.upper()}"


def _validate_required_scenarios(results: tuple[SyntheticScenarioResult, ...]) -> None:
    expected = tuple(SyntheticScenarioId)
    actual = tuple(result.scenario_id for result in results)
    if actual != expected:
        raise ValueError(
            "scenario_results must contain each required scenario exactly once in order"
        )


def _validate_result_traceability(result: SyntheticScenarioResult) -> None:
    traceability = set(result.traceability)
    labels = set(result.stress_labels)
    if "FR-012" not in traceability:
        raise ValueError("synthetic scenario result traceability must include FR-012")

    if result.scenario_id is SyntheticScenarioId.CRASH:
        if "RISK-001" not in traceability or labels.isdisjoint(
            {"market_drawdown", "drawdown_stress", "market_stress"}
        ):
            raise ValueError("crash scenario must include RISK-001 market drawdown evidence")
    if result.scenario_id is SyntheticScenarioId.SPREAD:
        if "RISK-002" not in traceability or "RISK-005" not in traceability:
            raise ValueError("spread scenario must include RISK-002 and RISK-005 traceability")
        if labels.isdisjoint({"cost_sensitivity", "liquidity_cost_stress"}):
            raise ValueError("spread scenario must include cost-sensitivity evidence")
    if result.scenario_id is SyntheticScenarioId.LIQUIDITY:
        if "RISK-002" not in traceability or labels.isdisjoint(
            {"liquidity_collapse", "insufficient_liquidity"}
        ):
            raise ValueError("liquidity scenario must include RISK-002 liquidity evidence")
    if result.scenario_id is SyntheticScenarioId.OUTAGE:
        if "RISK-002" not in traceability or labels.isdisjoint(
            {"fail_closed", "venue_outage"}
        ):
            raise ValueError("outage scenario must include RISK-002 fail-closed evidence")
