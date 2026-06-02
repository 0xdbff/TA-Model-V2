# Automated Asset-Agnostic Trading Intelligence System — Specification Bundle

This repository contains a complete project model for a validation-first, asset-agnostic trading intelligence system.

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
| `10_implementation_roadmap.md` | Staged implementation roadmap, sprint sequence, validation strategy, QA strategy, and integration strategy. |
| `11_tech_stack_and_docker.md` | Early technical stack choice and Docker/Compose runtime plan. |
| `12_sprint_execution_playbook.md` | Sprint operating mechanics, evidence packets, QA approach, and integration playbook. |
| `13_github_issue_backlog.md` | GitHub milestone, label, issue, and requirement-coverage pack. |
| `decision_records/` | Sprint and governance decision records for scope, universe, benchmarks, sources, stack, and gate assumptions. |
| `rules/00_delivery_anti_drift_rules.md` | Binding anti-drift rules for scope, stack, validation, QA, integration, and model/data drift. |

## GitHub workflow aids

Issue templates live in `.github/ISSUE_TEMPLATE/` and require requirement traceability, Docker/runtime impact, validation evidence, integration path, and anti-drift checks.

## Operating principle

The system is not a “market predictor.” It is a probabilistic decision and risk-control platform. No model, strategy, or execution path may enter live trading until it passes data-quality, simulation, walk-forward, paper-trading, and risk-control gates.
