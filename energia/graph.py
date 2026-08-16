"""Agente LangGraph stateful que consume herramientas vía MCP."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Literal, Optional, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

ROOT = Path(__file__).resolve().parents[1]
SERVER_MODULE = "energia.mcp_server"

SYSTEM_PROMPT = (
    "Eres un analista de demanda energética para Austria (ENTSO-E). "
    "Usa las herramientas MCP cuando necesites cifras del dataset. "
    "Si una herramienta devuelve ok=false o un error, explícalo al usuario "
    "y propone un intervalo válido (2019-07-25 a 2020-10-06) en lugar de inventar números."
)


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


def server_config() -> dict:
    return {
        "energia": {
            "command": sys.executable,
            "args": ["-m", SERVER_MODULE],
            "transport": "stdio",
            "cwd": str(ROOT),
        }
    }


def build_graph(llm_with_tools, tools_map):
    async def agent_node(state: AgentState):
        response = await llm_with_tools.ainvoke(state["messages"])
        return {"messages": [response]}

    async def tools_node(state: AgentState):
        last = state["messages"][-1]
        results = []
        for call in last.tool_calls:
            tool_fn = tools_map.get(call["name"])
            if tool_fn is None:
                content = f"Error: herramienta desconocida '{call['name']}'"
            else:
                try:
                    content = str(await tool_fn.ainvoke(call["args"]))
                except Exception as exc:
                    content = (
                        f"Error ejecutando '{call['name']}': {exc}. "
                        "No uses este resultado como si fuera un dato válido."
                    )
            results.append(ToolMessage(content=content, tool_call_id=call["id"]))
        return {"messages": results}

    def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
        if getattr(state["messages"][-1], "tool_calls", None):
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


async def run_agent(
    query: str,
    llm,
    system_prompt: Optional[str] = SYSTEM_PROMPT,
) -> str:
    """Abre sesión MCP, carga tools remotas y ejecuta el ciclo ReAct."""
    client = MultiServerMCPClient(server_config())
    async with client.session("energia") as session:
        tools = await load_mcp_tools(session)
        llm_with_tools = llm.bind_tools(tools)
        tools_map = {t.name: t for t in tools}
        app = build_graph(llm_with_tools, tools_map)
        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=query))
        result = await app.ainvoke({"messages": messages})
        return result["messages"][-1].content
