"""Traza de los flujos de evidencia de la semana 2.

Imprime, para cada flujo: la entrada del usuario, cada decisión del agente con
sus argumentos, el resultado que devolvió el servidor MCP y la respuesta final.
Cubre lo que exige la rúbrica: dos flujos completos de tool calling y el manejo
explícito de un error (una brecha que bloquea la acción).

El LLM está guionizado (`ScriptedLLM`) para que la evidencia sea reproducible
sin depender de Ollama; el servidor MCP, las herramientas, la autenticación y
las validaciones son reales.

Uso:  python -m centro.evidencia_flujo
      python -m centro.evidencia_flujo 2     (un solo flujo)
"""

from __future__ import annotations

import asyncio
import json
import sys

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from centro.graph import SYSTEM_PROMPT, build_graph, server_config
from centro.scripted_llm import ScriptedLLM

SEP = "=" * 78
CAMPOS_LARGOS = {"texto"}


def _llamada(nombre: str, args: dict, id_: str) -> dict:
    return {"name": nombre, "args": args, "id": id_, "type": "tool_call"}


def _decide(*llamadas: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=list(llamadas))


def _formatear_resultado(contenido: str) -> str:
    """Reindenta el JSON de una herramienta y recorta los campos de texto largo."""
    try:
        payload = json.loads(contenido)
    except (json.JSONDecodeError, TypeError):
        return str(contenido)
    if isinstance(payload, dict):
        payload = {
            k: (f"<{len(str(v))} caracteres de texto markdown>" if k in CAMPOS_LARGOS else v)
            for k, v in payload.items()
        }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _imprimir_traza(mensajes) -> None:
    for msg in mensajes:
        tipo = msg.__class__.__name__
        if tipo == "HumanMessage":
            print(f"\n[ENTRADA DEL USUARIO]\n{msg.content}")
        elif tipo == "AIMessage" and getattr(msg, "tool_calls", None):
            for call in msg.tool_calls:
                args = {
                    k: (v[:12] + "…" if k == "token" and isinstance(v, str) else v)
                    for k, v in call["args"].items()
                }
                print("\n[DECISIÓN DEL AGENTE] -> invocar herramienta")
                print(f"  herramienta: {call['name']}")
                print(f"  argumentos : {json.dumps(args, ensure_ascii=False)}")
        elif tipo == "ToolMessage":
            print("\n[RESULTADO DEL SERVIDOR MCP]")
            for linea in _formatear_resultado(msg.content).splitlines():
                print(f"  {linea}")
        elif tipo == "AIMessage":
            print(f"\n[RESPUESTA FINAL DEL AGENTE]\n{msg.content}")


async def _ejecutar(titulo: str, contexto: str, pregunta: str, llm) -> None:
    print(SEP)
    print(titulo)
    print(SEP)
    print(contexto)
    client = MultiServerMCPClient(server_config())
    async with client.session("centro") as session:
        tools = await load_mcp_tools(session)
        print(f"\n[HANDSHAKE MCP] {len(tools)} herramientas descubiertas:")
        print(f"  {', '.join(t.name for t in tools)}")
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


# ==========================================================================
# Flujo 1 — consulta pública: se responde sin pedir identidad
# ==========================================================================


async def flujo_1() -> None:
    llm = ScriptedLLM(
        [
            _decide(_llamada("consultar_convocatoria", {"consulta": "BID-2026-EDU-014"}, "f1")),
            AIMessage(
                content=(
                    "Las bases de la BID-2026-EDU-014 (fuente pública, sin necesidad de "
                    "identificarte) piden tener en cuenta dos condiciones antes de "
                    "postularse:\n\n"
                    "1. CONSORCIO. Exige un consorcio con al menos una universidad de otro "
                    "país miembro del BID; las propuestas de una sola institución no quedan "
                    "habilitadas.\n"
                    "2. OVERHEAD. La convocatoria reconoce un máximo del 12% de costos "
                    "indirectos y el mínimo institucional para organismos internacionales es "
                    "15% (POL-FIN-001): hay una brecha de 3 puntos que solo levanta una "
                    "exención de la Vicerrectoría.\n\n"
                    "Cierra el 30 de septiembre de 2026. Si aun así quieres postularte, la "
                    "Dirección tendría que tramitar la exención y conseguir la universidad "
                    "socia antes de esa fecha."
                )
            ),
        ]
    )
    await _ejecutar(
        "FLUJO 1 — Consulta pública: responder sin pedir identidad",
        "Usuario: cualquiera (aún sin autenticar).",
        "¿Qué pide la convocatoria del BID de innovación en educación superior?",
        llm,
    )


# ==========================================================================
# Flujo 2 — postulación completa: autenticar -> leer bases -> crear solicitud
# ==========================================================================


async def flujo_2() -> None:
    llm = ScriptedLLM(
        [
            _decide(_llamada("autenticar", {"cedula": "1080901234", "clave": "3846"}, "g1")),
            _decide(_llamada("consultar_convocatoria", {"consulta": "MINCIENCIAS-2026-CEA-003"}, "g2")),
            _decide(
                _llamada(
                    "crear_solicitud",
                    {
                        "token": "<TOKEN>",
                        "convocatoria_id": "MINCIENCIAS-2026-CEA-003",
                        "rol_propuesto": "investigador principal",
                        "justificacion": (
                            "Acredita 7 publicaciones en los últimos 5 años (la convocatoria "
                            "exige 3) y dedicación de tiempo completo, requisito del "
                            "investigador principal. Su experticia en desarrollo económico y "
                            "política pública coincide con el objeto de la convocatoria."
                        ),
                    },
                    "g3",
                )
            ),
            AIMessage(
                content=(
                    "Listo, Ricardo: tu solicitud quedó creada con el identificador SOL-0005 "
                    "(confirmado por la herramienta).\n\n"
                    "Contrasté las bases de MINCIENCIAS-2026-CEA-003 (fuente pública) con tu "
                    "perfil (dato interno, tras autenticarte):\n"
                    "- Publicaciones: exige 3 en los últimos 5 años; tu perfil registra 7.\n"
                    "- Dedicación: exige tiempo completo para el rol principal; la tuya lo es.\n"
                    "- Experticia: desarrollo económico y política pública, el área de la "
                    "convocatoria.\n\n"
                    "La solicitud queda en estado pendiente: tú te postulas, la asignación "
                    "final del equipo la decide la Dirección del Centro."
                )
            ),
        ]
    )
    await _ejecutar(
        "FLUJO 2 — Postulación: autenticar, contrastar el perfil y crear la solicitud",
        "Usuario: Ricardo Tovar, investigador (rol personal).",
        "¿Puedo aplicar a la convocatoria de Minciencias de ciencias económicas y administrativas?",
        llm,
    )


# ==========================================================================
# Flujo 3 — manejo de error: la brecha de overhead bloquea la solicitud
# ==========================================================================


async def flujo_3() -> None:
    llm = ScriptedLLM(
        [
            _decide(_llamada("autenticar", {"cedula": "1030456789", "clave": "2964"}, "h1")),
            _decide(
                _llamada(
                    "crear_solicitud",
                    {
                        "token": "<TOKEN>",
                        "convocatoria_id": "BID-2026-EDU-014",
                        "rol_propuesto": "investigadora principal",
                        "justificacion": "Mi experticia en educación superior encaja con el objeto.",
                    },
                    "h2",
                )
            ),
            AIMessage(
                content=(
                    "No pude crear la solicitud, Carolina, y la razón es concreta: la "
                    "herramienta devolvió ok=false con brecha de OVERHEAD. La convocatoria "
                    "del BID reconoce un máximo del 12% de costos indirectos y el mínimo "
                    "institucional para organismos internacionales es del 15% (POL-FIN-001).\n\n"
                    "Mientras esa brecha exista, postularse sería invertir tiempo en una "
                    "propuesta inhabilitada. La exención solo puede tramitarla la Dirección "
                    "ante la Vicerrectoría de Investigación: te sugiero plantearlo allí antes "
                    "de intentar la postulación de nuevo. No quedó registrada ninguna solicitud."
                )
            ),
        ]
    )
    await _ejecutar(
        "FLUJO 3 — Manejo de error: ok=false con brecha de overhead, no se crea nada",
        "Usuario: Carolina Pérez, investigadora (rol personal).",
        "Créame la solicitud para la convocatoria del BID de educación superior.",
        llm,
    )


FLUJOS = {"1": flujo_1, "2": flujo_2, "3": flujo_3}


async def main() -> None:
    pedidos = sys.argv[1:] or list(FLUJOS)
    for clave in pedidos:
        funcion = FLUJOS.get(clave)
        if funcion is None:
            print(f"Flujo desconocido: {clave}. Opciones: {', '.join(FLUJOS)}")
            continue
        await funcion()


if __name__ == "__main__":
    asyncio.run(main())
