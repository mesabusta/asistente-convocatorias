"""Agente LangGraph stateful que consume las herramientas vía MCP.

El grafo es el mismo ciclo ReAct de siempre — `agent ⇄ tools` con una arista
condicional — pero el caso de negocio le agrega una exigencia: el número de
iteraciones no lo fija el diseño, lo fija lo que van devolviendo las
herramientas. Una consulta pública se resuelve en un turno; una postulación
necesita autenticar, leer el perfil, leer la convocatoria, leer la política y
recién entonces decidir.

No hay herramientas locales declaradas aquí: todas se descubren en tiempo de
ejecución con `load_mcp_tools()` contra el servidor.
"""

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
SERVER_MODULE = "centro.mcp_server"

#: Tope de iteraciones del ciclo. Evita que un modelo que insiste en una
#: herramienta que siempre falla deje el grafo girando indefinidamente.
MAX_ITERACIONES = 12

SYSTEM_PROMPT = (
    "Eres el asistente del Centro de Proyectos y Consultoría de la Universidad de los "
    "Alpes. Ayudas a evaluar convocatorias de financiación y a conformar equipos.\n\n"
    "Antes de actuar, evalúa la intención del mensaje:\n"
    "1. Si la pregunta se resuelve con información pública — el contenido de una "
    "convocatoria o de una política — respóndela de inmediato con buscar_convocatorias, "
    "leer_convocatoria o consultar_politica. No pidas identidad.\n"
    "2. Si la gestión requiere datos internos del Centro (perfiles, historial, "
    "solicitudes) o ejecutar una acción, autentica primero con cédula y clave.\n\n"
    "Respeta los roles sin excepción. El personal consulta su propio perfil y crea "
    "solicitudes; nunca ve datos de otros ni se asigna a sí mismo. Solo un directivo "
    "lista al personal, revisa solicitudes y asigna una convocatoria a un equipo.\n\n"
    "Nunca inventes el contenido de una convocatoria, un perfil o una política: todo "
    "sale de una herramienta. Nunca afirmes que una solicitud quedó creada o que una "
    "convocatoria fue asignada sin la confirmación explícita de la herramienta que lo "
    "ejecutó. Si una herramienta devuelve ok=false, explica la brecha concreta en lugar "
    "de rechazar de forma genérica.\n\n"
    "Si detectas riesgo reputacional, una brecha que no puedes resolver o un caso "
    "ambiguo, no decidas: usa escalar_a_humanos con un resumen de lo evaluado, las "
    "brechas encontradas y las preguntas que requieren juicio humano.\n\n"
    "Distingue siempre en tu respuesta qué proviene de fuentes públicas y qué de datos "
    "internos autenticados. Toda decisión va acompañada de su justificación."
)


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


def server_config() -> dict:
    return {
        "centro": {
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
                content = (
                    f'{{"ok": false, "error": "Herramienta desconocida: {call["name"]}"}}'
                )
            else:
                try:
                    content = str(await tool_fn.ainvoke(call["args"]))
                except Exception as exc:
                    content = (
                        f'{{"ok": false, "error": "Fallo ejecutando {call["name"]}: {exc}. '
                        f'No uses este resultado como si fuera un dato válido."}}'
                    )
            results.append(ToolMessage(content=content, tool_call_id=call["id"]))
        return {"messages": results}

    def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
        if len(state["messages"]) > MAX_ITERACIONES * 2:
            return END
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
    """Abre sesión MCP, descubre las herramientas y ejecuta el ciclo ReAct."""
    estado = await run_agent_estado(query, llm, system_prompt)
    return estado["messages"][-1].content


async def run_agent_estado(
    query: str,
    llm,
    system_prompt: Optional[str] = SYSTEM_PROMPT,
) -> dict:
    """Igual que `run_agent` pero devuelve el estado completo.

    La evidencia de la wiki necesita el historial de mensajes, no solo la
    respuesta final: hay que poder mostrar la decisión, los argumentos y el
    resultado de cada herramienta.
    """
    client = MultiServerMCPClient(server_config())
    async with client.session("centro") as session:
        tools = await load_mcp_tools(session)
        llm_with_tools = llm.bind_tools(tools)
        app = build_graph(llm_with_tools, {t.name: t for t in tools})
        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=query))
        return await app.ainvoke({"messages": messages})
