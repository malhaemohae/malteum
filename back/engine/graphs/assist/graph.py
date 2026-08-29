"""assist 그래프: route → retrieve → generate → guard."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from engine.graphs.assist.nodes import Deps, make_nodes
from engine.graphs.assist.state import AssistState


def build_graph(deps: Deps):
    route, retrieve, generate, guard = make_nodes(deps)
    g = StateGraph(AssistState)
    g.add_node("route", route)
    g.add_node("retrieve", retrieve)
    g.add_node("generate", generate)
    g.add_node("guard", guard)
    g.set_entry_point("route")
    g.add_edge("route", "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", "guard")
    g.add_edge("guard", END)
    return g.compile()
