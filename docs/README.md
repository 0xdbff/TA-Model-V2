# Automated Asset-Agnostic Trading Intelligence System — Specification Bundle

This ZIP contains a complete project model for a validation-first, asset-agnostic trading intelligence system.

## Files

| File | Purpose |
|---|---|
| `01_project_spec.md` | Main product and technical specification with the requested 20 sections. |
| `02_requirements_catalog.csv` | Testable P0/P1/P2 functional and non-functional requirements. |
| `03_user_stories.csv` | User stories with measurable acceptance criteria. |
| `04_risk_register.csv` | Risk register covering market, model, data, execution, compliance, and operations. |
| `05_metrics_validation_matrix.csv` | Validation metrics, thresholds, owners, and promotion gates. |
| `06_architecture.mmd` | Mermaid architecture diagram. |
| `07_data_contracts.md` | Data schemas, quality gates, lineage, and retention plan. |
| `08_mvp_backlog.md` | MVP scope, delivery phases, and P0 backlog. |
| `09_references.md` | Regulatory and risk-management references used for control design. |

## Operating principle

The system is not a “market predictor.” It is a probabilistic decision and risk-control platform. No model, strategy, or execution path may enter live trading until it passes data-quality, simulation, walk-forward, paper-trading, and risk-control gates.
