"""Execution gateway, paper accounting, and TCA builders."""

from ta_model.execution.gateway import run_paper_gateway_replay, run_simulator_gateway_replay
from ta_model.execution.paper import make_paper_account_session_report, make_paper_tca_report

__all__ = [
    "make_paper_account_session_report",
    "make_paper_tca_report",
    "run_paper_gateway_replay",
    "run_simulator_gateway_replay",
]
