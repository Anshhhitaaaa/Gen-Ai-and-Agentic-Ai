"""
app/core/agent/planner.py

The Planner Agent — the piece that decides WHICH of your RAG functions
to call for a given question. Built with LangGraph's StateGraph.

This does NOT reimplement retrieval or generation — it only routes to
functions you already built and tested in app/core/rag/generate.py.
"""

from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END

from app.core.rag.generate import ask_mentor_smart, ask_about_repo, ask_ui_ux_review


class PlannerState(TypedDict):
    question: str
    repo_id: Optional[str]
    route: Optional[str]
    answer: Optional[str]
    sources: Optional[list]


# Simple keyword-based routing. Fast, transparent, and easy to explain
# in a demo. Can be upgraded later to an LLM-based classifier for more
# nuance — not necessary for this to be a genuine working agent today.
_REPO_SIGNALS = [
    "my code", "my repo", "my project", "this file", "this function",
    "review my", "my backend", "my auth", "bug in my", "explain this",
    "my implementation", "my repository",
]
_UI_UX_SIGNALS = [
    "ui", "ux", "design", "layout", "component", "frontend look",
    "user interface", "user experience", "styling", "css", "tailwind",
]


def _classify(state: PlannerState) -> PlannerState:
    question = state["question"].lower()

    if any(w in question for w in _UI_UX_SIGNALS):
        state["route"] = "ui_ux"
    elif state.get("repo_id") and any(w in question for w in _REPO_SIGNALS):
        state["route"] = "repo"
    else:
        state["route"] = "general"

    return state


def _answer_general(state: PlannerState) -> PlannerState:
    result = ask_mentor_smart(state["question"])
    state["answer"] = result["answer"]
    state["sources"] = result["sources"]
    return state


def _answer_repo(state: PlannerState) -> PlannerState:
    result = ask_about_repo(state["question"], state["repo_id"])
    state["answer"] = result["answer"]
    state["sources"] = result["sources"]
    return state


def _answer_ui_ux(state: PlannerState) -> PlannerState:
    result = ask_ui_ux_review(state["question"], state.get("repo_id"))
    state["answer"] = result["answer"]
    state["sources"] = result["guideline_sources"] + result["code_sources"]
    return state


def _route_decision(state: PlannerState) -> str:
    return state["route"]


def _build_graph():
    graph = StateGraph(PlannerState)
    graph.add_node("classify", _classify)
    graph.add_node("answer_general", _answer_general)
    graph.add_node("answer_repo", _answer_repo)
    graph.add_node("answer_ui_ux", _answer_ui_ux)

    graph.set_entry_point("classify")
    graph.add_conditional_edges(
        "classify",
        _route_decision,
        {
            "general": "answer_general",
            "repo": "answer_repo",
            "ui_ux": "answer_ui_ux",
        },
    )
    graph.add_edge("answer_general", END)
    graph.add_edge("answer_repo", END)
    graph.add_edge("answer_ui_ux", END)

    return graph.compile()


_agent = None


def get_agent():
    global _agent
    if _agent is None:
        _agent = _build_graph()
    return _agent


def ask_planner(question: str, repo_id: str = None) -> dict:
    """
    THIS is the main entry point for the whole agentic system.
    The agent decides internally which RAG system(s) to use.

    Returns:
        {"answer": str, "sources": list[str], "route_used": str}
    """
    agent = get_agent()
    result = agent.invoke({"question": question, "repo_id": repo_id})
    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "route_used": result["route"],
    }