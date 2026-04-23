"""Profile matching node implementation."""

from __future__ import annotations

from core.graph.nodes.base import WorkflowNode
from core.ranking.scorer import match_against_profile
from core.schemas import AgentState, CareerStateMemory, ProfileMemory


class MatchProfileNode(WorkflowNode):
    """
    Load memory and compute profile fit against the extracted signal.

    Input fields:
    - `extracted_signal`
    - `user_id`
    - `workspace_id`

    Output fields:
    - `profile_memory`
    - `career_state_memory`
    - `profile_match`
    - `model_routing["match_profile"]`

    Failure strategy:
    - If extraction is missing, return partial state with a structured failure.
    """

    name = "match_profile"

    def _run_impl(self, state: AgentState) -> AgentState:
        if state.extracted_signal is None:
            raise ValueError("extracted_signal is required before match_profile.")

        loaded_memory = self.dependencies.memory_provider.load(
            user_id=state.user_id, workspace_id=state.workspace_id
        )
        state.profile_memory = ProfileMemory.model_validate(loaded_memory["profile_memory"])
        state.career_state_memory = CareerStateMemory.model_validate(
            loaded_memory["career_state_memory"]
        )
        state.model_routing[self.name] = self.dependencies.model_router.select(
            "match_profile", "medium"
        )
        state.profile_match = match_against_profile(
            state.extracted_signal, state.profile_memory
        )
        return state
