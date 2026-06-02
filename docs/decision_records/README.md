# Decision Records

This directory stores sprint and governance decision records that lock product,
risk, validation, Docker/runtime, and implementation assumptions before later
work depends on them.

Decision records are binding delivery artifacts once approved through the linked
GitHub issue/PR review. Changes that affect MVP scope, validation criteria,
risk limits, Docker/runtime choices, data/source legality, or benchmark policy
must follow the change-control rules in
`docs/rules/00_delivery_anti_drift_rules.md`.

## Current records

| Record | Purpose |
|---|---|
| `S0-001_mvp_universe_venues_benchmarks.md` | Locks the MVP spot universe assumptions, venue/source candidates, and benchmark policy. |
| `S0-002_technical_stack_and_docker_profiles.md` | Approves the Python-first stack and Docker Compose profile plan. |
| `S0-003_risk_limit_policy_and_kill_switch_states.md` | Defines initial risk-limit policy and kill-switch states. |
| `S0-004_source_license_register_workflow.md` | Defines the source/license register workflow and source approval states. |
| `S0-005_ci_evidence_gates_and_artifact_locations.md` | Defines CI evidence gates, failure semantics, and artifact locations. |
