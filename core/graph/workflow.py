"""Minimal workflow graph built for step 3."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from core.graph.nodes import (
    ClassifyNode,
    ExtractNode,
    IngestNode,
    MatchProfileNode,
    NormalizeNode,
    PersistNode,
    ReminderPlanNode,
    RenderNode,
    ScoreNode,
)
from core.runtime.dependencies import WorkflowDependencies
from core.schemas import AgentState, MemoryWriteMode, SourceType

NODE_ORDER = [
    "ingest",
    "normalize",
    "classify",
    "extract",
    "match_profile",
    "score",
    "reminder_plan",
    "persist",
    "render",
]


class JobWorkflow:
    """
    Minimal single-agent workflow wrapper for local execution and LangGraph.

    Responsibilities:
    - Instantiate nodes with shared dependencies.
    - Provide sequential execution for local tests and environments without LangGraph.
    - Build a LangGraph version when the dependency is available.

    Non-responsibilities:
    - API request handling.
    - Persistent storage configuration.
    """

    def __init__(self, dependencies: WorkflowDependencies | None = None) -> None:
        self.dependencies = dependencies or WorkflowDependencies()
        self.nodes = {
            "ingest": IngestNode(self.dependencies),
            "normalize": NormalizeNode(self.dependencies),
            "classify": ClassifyNode(self.dependencies),
            "extract": ExtractNode(self.dependencies),
            "match_profile": MatchProfileNode(self.dependencies),
            "score": ScoreNode(self.dependencies),
            "reminder_plan": ReminderPlanNode(self.dependencies),
            "persist": PersistNode(self.dependencies),
            "render": RenderNode(self.dependencies),
        }

    def run_sequential(self, state: AgentState) -> AgentState:
        """Execute the workflow node by node without requiring LangGraph."""

        current_state = state
        for node_name in NODE_ORDER:
            current_state = self.nodes[node_name].execute(current_state)
        return current_state

    def build_langgraph(self):
        """Build and compile the LangGraph workflow."""

        try:
            from langgraph.graph import END, StateGraph
        except ImportError as exc:  # pragma: no cover - depends on local env
            raise ImportError(
                "LangGraph is not installed. Use run_sequential() or install dependencies."
            ) from exc

        builder = StateGraph(AgentState)
        for node_name in NODE_ORDER:
            builder.add_node(node_name, self.nodes[node_name].as_langgraph_node())

        for current_node, next_node in zip(NODE_ORDER[:-1], NODE_ORDER[1:]):
            builder.add_edge(current_node, next_node)

        builder.set_entry_point("ingest")
        builder.add_edge("render", END)
        return builder.compile()

    def invoke(self, state: AgentState, prefer_langgraph: bool = True) -> AgentState:
        """Run the workflow, using LangGraph when available and requested."""

        if prefer_langgraph:
            try:
                graph = self.build_langgraph()
                result = graph.invoke(state.model_dump(mode="python"))
                return AgentState.model_validate(result)
            except ImportError:
                return self.run_sequential(state)

        return self.run_sequential(state)


def create_initial_state(
    raw_input: str,
    source_type: SourceType,
    user_id: str = "demo_user",
    workspace_id: str | None = "demo_workspace",
    source_ref: str | None = None,
    memory_write_mode: MemoryWriteMode = MemoryWriteMode.CONTEXT_ONLY,
    source_metadata: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> AgentState:
    """Create the minimal state payload required to start the workflow."""

    return AgentState(
        trace_id=trace_id or f"trace_{uuid4().hex[:10]}",
        user_id=user_id,
        workspace_id=workspace_id,
        source_type=source_type,
        source_ref=source_ref,
        source_metadata=source_metadata or {},
        memory_write_mode=memory_write_mode,
        raw_input=raw_input,
    )
