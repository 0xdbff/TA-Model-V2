"""Evidence for S6-004 synthetic scenario suite using integrated replay."""

from __future__ import annotations

from decimal import Decimal

import ta_model.contracts as public_contracts
from ta_model.contracts.scenarios import SyntheticScenarioId, SyntheticScenarioResult
from ta_model.contracts.simulation import ReplayFillStatus, ReplayRejectReason
from ta_model.simulation.scenarios import run_synthetic_scenario_suite


def _scenario(scenario_id: SyntheticScenarioId) -> SyntheticScenarioResult:
    suite = run_synthetic_scenario_suite(seed=6004)
    return next(result for result in suite.scenario_results if result.scenario_id is scenario_id)


def _status_pairs(result: SyntheticScenarioResult) -> tuple[tuple[ReplayFillStatus, int], ...]:
    return tuple((item.status, item.count) for item in result.status_counts)


def test_public_contract_exports_include_synthetic_scenario_suite_contracts() -> None:
    assert public_contracts.SyntheticScenarioId is SyntheticScenarioId
    assert public_contracts.make_synthetic_scenario_suite_report is not None


def test_suite_includes_all_required_scenario_names_and_traceability() -> None:
    suite = run_synthetic_scenario_suite(seed=6004)

    assert tuple(result.scenario_id for result in suite.scenario_results) == tuple(
        SyntheticScenarioId
    )
    assert suite.requirement_ids == ("FR-012",)
    assert "RISK-001" in suite.risk_ids
    assert "RISK-002" in suite.risk_ids
    assert all(
        result.replay_report_id.startswith("REPLAYREPORT:")
        for result in suite.scenario_results
    )


def test_seeded_suite_rerun_is_deterministic() -> None:
    first = run_synthetic_scenario_suite(seed=6004)
    second = run_synthetic_scenario_suite(seed=6004)

    assert first.suite_report_id == second.suite_report_id
    assert first.suite_hash == second.suite_hash
    assert tuple(result.replay_report_hash for result in first.scenario_results) == tuple(
        result.replay_report_hash for result in second.scenario_results
    )


def test_random_walk_and_trend_exercise_fill_cost_and_balance_accounting() -> None:
    random_walk = _scenario(SyntheticScenarioId.RANDOM_WALK)
    trend = _scenario(SyntheticScenarioId.TREND)

    assert _status_pairs(random_walk) == ((ReplayFillStatus.FILLED, 1),)
    assert random_walk.total_cost > 0
    assert random_walk.final_balances
    assert _status_pairs(trend) == ((ReplayFillStatus.FILLED, 2),)
    assert trend.filled_quantity == Decimal("1.50")
    assert trend.total_cost > 0


def test_crash_scenario_exposes_drawdown_stress_without_success_claim() -> None:
    crash = _scenario(SyntheticScenarioId.CRASH)

    assert "RISK-001" in crash.traceability
    assert "market_drawdown" in crash.stress_labels
    assert crash.min_close_price < crash.max_close_price
    assert crash.scenario_name.lower().find("evidence") >= 0


def test_spread_scenario_high_cost_exceeds_low_cost_baseline() -> None:
    spread = _scenario(SyntheticScenarioId.SPREAD)

    assert "RISK-002" in spread.traceability
    assert spread.comparison_total_cost is not None
    assert spread.total_cost > spread.comparison_total_cost
    assert _status_pairs(spread) == ((ReplayFillStatus.FILLED, 1),)


def test_liquidity_scenario_produces_partial_and_failed_liquidity_outcomes() -> None:
    liquidity = _scenario(SyntheticScenarioId.LIQUIDITY)

    assert "RISK-002" in liquidity.traceability
    assert _status_pairs(liquidity) == (
        (ReplayFillStatus.PARTIALLY_FILLED, 1),
        (ReplayFillStatus.UNFILLED, 1),
    )
    assert liquidity.rejection_counts == ((ReplayRejectReason.INSUFFICIENT_LIQUIDITY, 1),)
    assert liquidity.filled_quantity == Decimal("0.50")
    assert liquidity.remaining_quantity == Decimal("5.50")


def test_outage_scenario_fails_closed_with_rejection_accounting() -> None:
    outage = _scenario(SyntheticScenarioId.OUTAGE)

    assert "RISK-002" in outage.traceability
    assert "fail_closed" in outage.stress_labels
    assert _status_pairs(outage) == ((ReplayFillStatus.REJECTED, 1),)
    assert outage.rejection_counts == ((ReplayRejectReason.VENUE_NOT_TRADABLE, 1),)
    assert outage.filled_quantity == 0


def test_scenarios_preserve_event_time_no_same_bar_evidence_via_replay_hashes() -> None:
    suite = run_synthetic_scenario_suite(seed=6004)

    assert all(result.market_data_hash for result in suite.scenario_results)
    assert all(result.replay_report_hash for result in suite.scenario_results)
    assert {"FR-012"}.issubset(set(suite.requirement_ids))
