# Paper-Readiness Observability Runbook

Scope: S10 paper-readiness dashboard and alert triage only. This runbook does not
authorize live capital, risk-limit widening, model promotion, or risk-engine bypass.

## Data health and stale feeds

- Check the linked `DataHealthSignal` and source stream-health event.
- Confirm affected source, venue, instrument, channel, and evaluation timestamp.
- Keep affected strategies/instruments blocked until freshness recovers and the
  source incident is understood.

## Model validation readiness

- Check the linked `ModelValidationReport` calibration, probabilistic metrics,
  reasons, and caveats.
- Do not promote or route a model from this alert. Open model review if calibration
  or validation blockers persist.

## Strategy gate and no-trade quality

- Check the linked `StrategyGateReport` no-trade utility delta, reason counts, and
  cost-drag evidence.
- Treat no-trade as first-class evidence; do not lower thresholds without review.

## Portfolio accounting and drawdown

- Check linked `PaperAccountSessionReport` account-state linkage, execution-cost
  totals, and risk-event drawdown telemetry.
- Reconcile account-state lineage before making a paper-readiness claim.

## Execution TCA and order rejects

- Check linked `PaperTcaReport`, `ExecutionGatewayReport`, and paper rejection logs.
- Investigate TCA issue rows, missing quotes, rejects, and cost prediction error;
  do not normalize repeat rejects as market noise.

## Risk kill-switch and pre-trade blocks

- Check linked `RiskCheckEvent` limit evaluations, reason codes, active kill state,
  and trace IDs.
- Kill-switch or hard-breach alerts remain blocking until risk owners clear the
  underlying condition with auditable evidence.
