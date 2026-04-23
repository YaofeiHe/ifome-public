"""Score node implementation."""

from __future__ import annotations

from core.graph.nodes.base import WorkflowNode
from core.ranking.scorer import score_signal
from core.schemas import AgentState


class ScoreNode(WorkflowNode):
    """
    Convert profile fit and urgency into a final ranking result.

    Input fields:
    - `extracted_signal`
    - `profile_match`

    Output fields:
    - `score_result`
    - `model_routing["score"]`

    Failure strategy:
    - Missing prerequisites produce partial-state failure.

    Notes:
    - The current POC uses explicit heuristics.
    - Later versions can upgrade this node to a rule + LLM hybrid scorer.
    """

    name = "score"

    def _run_impl(self, state: AgentState) -> AgentState:
        if state.extracted_signal is None or state.profile_match is None:
            raise ValueError("extracted_signal and profile_match are required before score.")

        state.model_routing[self.name] = "hybrid_rule_mock"
        state.score_result = score_signal(state.extracted_signal, state.profile_match)
        return state
