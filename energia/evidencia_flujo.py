"""Traza completa de un flujo agéntico para la evidencia de la wiki.

A diferencia de `demo_flujos.py` (que solo imprime la respuesta final), este
script recorre el historial de mensajes e imprime cada paso del ciclo ReAct:
entrada del usuario, decisión de invocar la tool, argumentos elegidos,
resultado devuelto por el servidor MCP y respuesta final construida a partir
de ese resultado.

Uso:  python -m energia.evidencia_flujo
"""

from __future__ import annotations

import asyncio
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from energia.graph import SYSTEM_PROMPT, build_graph, server_config
from energia.scripted_llm import ScriptedLLM

SEP = "=" * 78


def _formatear(contenido: str) -> str:
    """Reindenta un JSON de tool para que sea legible en la wiki."""
    try:
        return json.dumps(json.loads(contenido), indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return str(contenido)


def _imprimir_traza(mensajes) -> None:
    for msg in mensajes:
        tipo = msg.__class__.__name__
        if tipo == "SystemMessage":
            print(f"\n[SYSTEM PROMPT]\n{msg.content}")
        elif tipo == "HumanMessage":
            print(f"\n[ENTRADA DEL USUARIO]\n{msg.content}")
        elif tipo == "AIMessage" and getattr(msg, "tool_calls", None):
            for call in msg.tool_calls:
                print("\n[DECISIÓN DEL AGENTE] -> invocar tool")
                print(f"  tool      : {call['name']}")
                print(f"  argumentos: {json.dumps(call['args'], ensure_ascii=False)}")
                print(f"  call_id   : {call['id']}")
        elif tipo == "ToolMessage":
            print("\n[RESULTADO DEL SERVIDOR MCP]")
            for linea in _formatear(msg.content).splitlines():
                print(f"  {linea}")
        elif tipo == "AIMessage":
            print(f"\n[RESPUESTA FINAL DEL AGENTE]\n{msg.content}")


async def _ejecutar(titulo: str, pregunta: str, llm) -> None:
    print(SEP)
    print(titulo)
    print(SEP)
    client = MultiServerMCPClient(server_config())
    async with client.session("energia") as session:
        tools = await load_mcp_tools(session)
        print(f"\n[HANDSHAKE MCP] tools descubiertas: {[t.name for t in tools]}")
        app = build_graph(llm.bind_tools(tools), {t.name: t for t in tools})
        estado = await app.ainvoke(
            {
                "messages": [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=pregunta),
                ]
            }
        )
        _imprimir_traza(estado["messages"])
    print()


async def main() -> None:
    await _ejecutar(
        "FLUJO A — consulta de demanda resuelta con una sola tool",
        "¿Cuál fue la demanda media entre 2019-08-01 y 2019-08-07?",
        ScriptedLLM(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "consultar_demanda",
                            "args": {"start": "2019-08-01", "end": "2019-08-07"},
                            "id": "call-demanda-1",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(
                    content=(
                        "Entre el 2019-08-01 y el 2019-08-07 se observaron 145 horas "
                        "con demanda real. El promedio fue de 6.237,79 MW, con un "
                        "mínimo de 4.176,00 MW y un máximo de 8.123,00 MW. Las cifras "
                        "provienen de la tool consultar_demanda; no fueron estimadas."
                    )
                ),
            ]
        ),
    )

    await _ejecutar(
        "FLUJO B — la tool devuelve ok=false y el agente corrige el intervalo",
        "Dame los 3 picos de demanda del 1 al 2 de enero de 2015. Si falla, usa agosto 2019.",
        ScriptedLLM(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "detectar_picos",
                            "args": {"start": "2015-01-01", "end": "2015-01-02", "n": 3},
                            "id": "call-picos-err",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "detectar_picos",
                            "args": {"start": "2019-08-01", "end": "2019-08-03", "n": 3},
                            "id": "call-picos-ok",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(
                    content=(
                        "El intervalo de enero de 2015 no existe en el dataset "
                        "(la serie arranca el 2019-07-25), por eso la tool devolvió "
                        "un error y no inventé cifras. Reconsulté agosto de 2019: los "
                        "tres picos fueron 8.123 MW el 2019-08-02 a las 11:00, "
                        "8.027 MW a las 10:00 y 7.961 MW a las 12:00 del mismo día."
                    )
                ),
            ]
        ),
    )


if __name__ == "__main__":
    asyncio.run(main())
