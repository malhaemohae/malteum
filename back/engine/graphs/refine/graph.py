"""refine 그래프.

candidates → correct → cache_lookup → (hit → collect | miss → l3_judge → cache_store → collect)
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from engine.graphs.refine.nodes import Deps, make_nodes
from engine.graphs.refine.state import RefineState


def build_graph(deps: Deps):
    candidates, correct, cache_lookup, l3_judge, cache_store, collect = make_nodes(deps)
    g = StateGraph(RefineState)
    g.add_node("candidates", candidates)
    g.add_node("correct", correct)
    g.add_node("cache_lookup", cache_lookup)
    g.add_node("l3_judge", l3_judge)
    g.add_node("cache_store", cache_store)
    g.add_node("collect", collect)
    g.set_entry_point("candidates")
    g.add_conditional_edges(
        "candidates",
        lambda s: "collect" if not s["candidates"] else "correct",
        {"collect": "collect", "correct": "correct"},
    )
    g.add_edge("correct", "cache_lookup")
    g.add_conditional_edges(
        "cache_lookup",
        lambda s: "collect" if s["cache_hit"] else "l3_judge",
        {"collect": "collect", "l3_judge": "l3_judge"},
    )
    g.add_edge("l3_judge", "cache_store")
    g.add_edge("cache_store", "collect")
    g.add_edge("collect", END)
    return g.compile()
