"""Audit trace contracts and seams for decision reconstruction.

Use ``run_audit_gate_validation`` as the public audit gate acceptance entrypoint;
it replays explicit trace IDs through a resolver before producing gate reports.
"""

from ta_model.audit.gate import (
    AuditGateRunConfig,
    AuditGateSampleMethod,
    AuditGateSamplePolicy,
    AuditGateToleranceMode,
    AuditGateTolerancePolicy,
    make_audit_gate_run_config,
    run_audit_gate_validation,
)
from ta_model.audit.replay import (
    DecisionTraceEvidenceResolver,
    DecisionTraceReplayBlocker,
    DecisionTraceReplayBlockerCode,
    DecisionTraceReplayEvidence,
    DecisionTraceReplayReport,
    DecisionTraceReplayStatus,
    InMemoryDecisionTraceEvidenceStore,
    replay_decision_trace_by_id,
)
from ta_model.audit.trace import (
    DecisionTraceEnvelope,
    ForecastTraceReference,
    StrategyOrderIntentBuildError,
    build_decision_trace_envelope_hash,
    build_decision_trace_envelope_id,
    build_order_intent_client_order_id,
    build_order_intent_from_strategy_decision,
    make_decision_trace_envelope,
)

__all__ = [
    "AuditGateRunConfig",
    "AuditGateSampleMethod",
    "AuditGateSamplePolicy",
    "AuditGateToleranceMode",
    "AuditGateTolerancePolicy",
    "DecisionTraceEvidenceResolver",
    "DecisionTraceEnvelope",
    "DecisionTraceReplayBlocker",
    "DecisionTraceReplayBlockerCode",
    "DecisionTraceReplayEvidence",
    "DecisionTraceReplayReport",
    "DecisionTraceReplayStatus",
    "ForecastTraceReference",
    "InMemoryDecisionTraceEvidenceStore",
    "StrategyOrderIntentBuildError",
    "build_decision_trace_envelope_hash",
    "build_decision_trace_envelope_id",
    "build_order_intent_client_order_id",
    "build_order_intent_from_strategy_decision",
    "make_audit_gate_run_config",
    "make_decision_trace_envelope",
    "replay_decision_trace_by_id",
    "run_audit_gate_validation",
]
