# Agent Instructions

- Read and follow `docs/rules/00_delivery_anti_drift_rules.md` before implementation work.
- Use `docs/02_requirements_catalog.csv` as the primary FR/NFR traceability source.
- Keep MVP scope to validated paper trading only: spot, liquid instruments, no leverage, no derivatives, no live capital.
- Preserve validation-first delivery: every issue/PR needs requirement IDs, acceptance evidence, Docker/runtime impact, and anti-drift checks.
- Do not bypass the independent risk engine, kill switch, event-time data rules, or trace/replay requirements.
- Prefer the stack in `docs/11_tech_stack_and_docker.md`; new runtime/datastore/broker choices require ADR approval.
- Treat no-trade as a first-class logged and evaluated decision.
- Stop work and surface blockers for lookahead leakage, secrets exposure, unapproved data, risk bypass, duplicate orders, replay failure, or moved validation assumptions.
