"""Traza completa de las cuatro situaciones del caso de negocio.

Imprime, para cada situación: la entrada del usuario, cada decisión del agente
con sus argumentos, el resultado que devolvió el servidor MCP y la respuesta
final construida a partir de esos resultados.

Uso:  python -m centro.evidencia_flujo
      python -m centro.evidencia_flujo A     (una sola situación)
"""

from __future__ import annotations

import asyncio
import json
import sys

from langchain_core.messages import AIMessage
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
        from langchain_core.messages import HumanMessage, SystemMessage

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
# Situación A — brecha de política, no se crea solicitud
# ==========================================================================


async def situacion_a() -> None:
    llm = ScriptedLLM(
        [
            _decide(_llamada("leer_convocatoria", {"convocatoria_id": "BID-2026-EDU-014"}, "a1")),
            _decide(_llamada("consultar_politica", {"tema": "overhead"}, "a2")),
            AIMessage(
                content=(
                    "No deberías postularte a la BID-2026-EDU-014 en las condiciones actuales. "
                    "Encontré dos brechas, ambas leídas de fuentes públicas:\n\n"
                    "1. CONSORCIO. Las bases exigen un consorcio con al menos una universidad "
                    "de otro país miembro del BID. Las propuestas de una sola institución no "
                    "son habilitadas, y el Centro no tiene ese socio constituido.\n\n"
                    "2. OVERHEAD. La convocatoria reconoce un máximo del 12% de costos "
                    "indirectos. La política POL-FIN-001 fija un mínimo institucional del 15% "
                    "para organismos internacionales. La brecha es de 3 puntos y solo la puede "
                    "levantar una exención de la Vicerrectoría de Investigación, trámite que "
                    "debe iniciar la Dirección del Centro.\n\n"
                    "Por eso no creé ninguna solicitud: mientras la brecha exista, postularse "
                    "sería invertir tiempo en una propuesta inhabilitada. El tema y tu perfil sí "
                    "encajan, así que vale la pena preguntarle a la Dirección si quiere tramitar "
                    "la exención y buscar la universidad socia."
                )
            ),
        ]
    )
    await _ejecutar(
        "SITUACIÓN A — Personal, brecha de política (consulta pública)",
        "Usuario: consultor de la sección de educación superior. Aún sin autenticar.",
        "¿Puedo postularme a la convocatoria del BID de innovación en educación superior?",
        llm,
    )


# ==========================================================================
# Situación B — el personal crea una solicitud
# ==========================================================================


async def situacion_b() -> None:
    llm = ScriptedLLM(
        [
            _decide(_llamada("autenticar", {"cedula": "1080901234", "clave": "3846"}, "b1")),
            _decide(_llamada("consultar_perfil", {"token": "<TOKEN>"}, "b2")),
            _decide(
                _llamada(
                    "leer_convocatoria", {"convocatoria_id": "MINCIENCIAS-2026-CEA-003"}, "b3"
                )
            ),
            _decide(
                _llamada(
                    "crear_solicitud",
                    {
                        "token": "<TOKEN>",
                        "convocatoria_id": "MINCIENCIAS-2026-CEA-003",
                        "rol_propuesto": "investigador principal",
                        "justificacion": (
                            "Acredita 7 publicaciones en los últimos 5 años (la convocatoria "
                            "exige 3) y tiene dedicación de tiempo completo, que es requisito "
                            "para el investigador principal. Su experticia en desarrollo "
                            "económico y política pública coincide con el objeto, y sus dos "
                            "evaluaciones de impacto previas terminaron con resultado exitoso."
                        ),
                    },
                    "b4",
                )
            ),
            AIMessage(
                content=(
                    "Listo, Ricardo: tu solicitud quedó creada con el identificador SOL-0005.\n\n"
                    "Verifiqué contra las bases de MINCIENCIAS-2026-CEA-003 (fuente pública) y "
                    "contra tu perfil (dato interno, tras autenticarte):\n"
                    "- Publicaciones: la convocatoria exige 3 en los últimos 5 años; tu perfil "
                    "registra 7.\n"
                    "- Dedicación: exige tiempo completo para el investigador principal; la tuya "
                    "es tiempo completo.\n"
                    "- Experticia: desarrollo económico y política pública, que es el área de la "
                    "convocatoria.\n"
                    "- No exige consorcio internacional, así que esa restricción no aplica.\n\n"
                    "La solicitud queda en estado pendiente. Importante: tú te postulas, no te "
                    "asignas. Quién queda finalmente en la propuesta lo decide la Dirección del "
                    "Centro contrastando todas las solicitudes contra los criterios de "
                    "evaluación."
                )
            ),
        ]
    )
    await _ejecutar(
        "SITUACIÓN B — Personal crea una solicitud (autenticación + perfil)",
        "Usuario: Ricardo Tovar, investigador de la sección de desarrollo económico.",
        "¿Puedo aplicar a la convocatoria de Minciencias de ciencias económicas y administrativas?",
        llm,
    )


# ==========================================================================
# Situación C — riesgo reputacional, escalar
# ==========================================================================


async def situacion_c() -> None:
    llm = ScriptedLLM(
        [
            _decide(_llamada("buscar_convocatorias", {"texto": "responsabilidad social"}, "c1")),
            _decide(
                _llamada(
                    "leer_convocatoria", {"convocatoria_id": "PETROANDINA-2026-RSE-002"}, "c2"
                )
            ),
            _decide(_llamada("consultar_politica", {"tema": "riesgo reputacional"}, "c3")),
            _decide(
                _llamada(
                    "escalar_a_humanos",
                    {
                        "motivo": (
                            "Riesgo reputacional: la entidad convocante pertenece al sector "
                            "extractivo y el estudio implica datos sensibles de comunidades. "
                            "La política POL-RIE-002 reserva esta valoración al Comité de Ética "
                            "y Reputación."
                        ),
                        "convocatoria_id": "PETROANDINA-2026-RSE-002",
                        "analisis_realizado": [
                            "Leí las bases: el objeto encaja con la sección de sostenibilidad.",
                            "La entidad opera en hidrocarburos y minería (sector restringido).",
                            "Registra procesos abiertos ante autoridades ambientales y pronunciamientos sobre consulta previa.",
                            "El estudio levanta información socioeconómica de hogares en comunidades.",
                            "El presupuesto se declara 'a convenir', sin valor de referencia público.",
                        ],
                        "brechas": [
                            "Sector extractivo: restricción del numeral 1 de POL-RIE-002.",
                            "Datos sensibles de comunidades: señal 3 de la misma política.",
                            "Sin monto de referencia: no se puede determinar el nivel de autorización (POL-GOB-003).",
                        ],
                        "preguntas_pendientes": [
                            "¿El Comité emite concepto favorable pese a los procesos ambientales abiertos?",
                            "¿Existe un marco de tratamiento de datos comunitarios aprobado para este tipo de levantamiento?",
                            "¿Qué valor estimado se usa para fijar el nivel de autorización con presupuesto a convenir?",
                        ],
                    },
                    "c4",
                )
            ),
            AIMessage(
                content=(
                    "Este caso no lo puedo resolver yo y no debo intentarlo: lo escalé al Comité "
                    "de Ética y Reputación.\n\n"
                    "El tema sí encaja con la sección de sostenibilidad, pero concurren tres "
                    "señales de la política POL-RIE-002: la entidad pertenece al sector "
                    "extractivo, registra procesos abiertos ante autoridades ambientales y el "
                    "estudio levanta datos sensibles de comunidades. A eso se suma que el "
                    "presupuesto está 'a convenir', lo que impide fijar el nivel de autorización.\n\n"
                    "La valoración reputacional no es una decisión técnica y la política es "
                    "explícita en que ningún sistema de apoyo puede concluir que una convocatoria "
                    "de sector restringido es viable. No creé solicitud ni asigné equipo.\n\n"
                    "El Comité recibe el análisis que alcancé a hacer, las tres brechas "
                    "identificadas y las preguntas concretas que quedan abiertas, para que no "
                    "tenga que rehacer el trabajo desde cero."
                )
            ),
        ]
    )
    await _ejecutar(
        "SITUACIÓN C — Riesgo reputacional: reconocer la señal y escalar",
        "Usuario: cualquiera. No hace falta autenticar para leer las bases y la política.",
        "¿Qué tal la convocatoria de la empresa del sector extractivo para el estudio de "
        "responsabilidad social? El presupuesto es a convenir.",
        llm,
    )


# ==========================================================================
# Situación D — la directiva asigna el equipo
# ==========================================================================


async def situacion_d() -> None:
    llm = ScriptedLLM(
        [
            _decide(_llamada("autenticar", {"cedula": "1010234567", "clave": "4821"}, "d1")),
            _decide(
                _llamada(
                    "leer_convocatoria", {"convocatoria_id": "MINCIENCIAS-2026-CEA-003"}, "d2"
                )
            ),
            _decide(
                _llamada(
                    "listar_solicitudes",
                    {"token": "<TOKEN>", "convocatoria_id": "MINCIENCIAS-2026-CEA-003"},
                    "d3",
                )
            ),
            _decide(_llamada("listar_personal", {"token": "<TOKEN>", "area": "politica_publica"}, "d4")),
            _decide(
                _llamada(
                    "asignar_convocatoria",
                    {
                        "token": "<TOKEN>",
                        "convocatoria_id": "MINCIENCIAS-2026-CEA-003",
                        "cedulas": ["1030456789", "1060789012"],
                        "justificacion": (
                            "El criterio de mayor peso es la trayectoria del investigador "
                            "principal (30%). Carolina Pérez acredita 5 publicaciones en los "
                            "últimos 5 años frente a las 3 exigidas, dedicación de tiempo "
                            "completo y dos evaluaciones de impacto previas con resultado "
                            "exitoso. Sebastián Cruz cubre el requisito de investigador de "
                            "apoyo con maestría y tiempo completo, y su trabajo previo en "
                            "sistematización de programas sociales aporta al criterio de "
                            "complementariedad del equipo (20%). Felipe Manrique queda por "
                            "fuera porque su dedicación es de medio tiempo."
                        ),
                    },
                    "d5",
                )
            ),
            AIMessage(
                content=(
                    "Convocatoria MINCIENCIAS-2026-CEA-003 asignada a Carolina Pérez como "
                    "investigadora principal y Sebastián Cruz como investigador de apoyo.\n\n"
                    "Cómo llegué a ese equipo, contra los criterios de evaluación de las bases:\n"
                    "- Trayectoria del investigador principal (30%, el de mayor peso): Carolina "
                    "tiene 5 publicaciones recientes frente a las 3 exigidas, tiempo completo y "
                    "dos evaluaciones de impacto previas con resultado exitoso.\n"
                    "- Composición y complementariedad del equipo (20%): Sebastián cumple el "
                    "requisito de apoyo con maestría y tiempo completo.\n"
                    "- Descarté a Felipe Manrique porque su dedicación es de medio tiempo, y la "
                    "convocatoria exige tiempo completo en el rol principal.\n\n"
                    "Las tres solicitudes quedaron actualizadas: dos asignadas y una como no "
                    "seleccionada."
                )
            ),
        ]
    )
    await _ejecutar(
        "SITUACIÓN D — Directiva revisa solicitudes y asigna el equipo",
        "Usuario: Luisa Ruiz, Coordinadora del Centro (rol directivo).",
        "¿A qué convocatoria puede aplicar mi personal de política pública y con qué equipo?",
        llm,
    )


SITUACIONES = {"A": situacion_a, "B": situacion_b, "C": situacion_c, "D": situacion_d}


async def main() -> None:
    pedidas = [a.upper() for a in sys.argv[1:]] or list(SITUACIONES)
    for clave in pedidas:
        funcion = SITUACIONES.get(clave)
        if funcion is None:
            print(f"Situación desconocida: {clave}. Opciones: {', '.join(SITUACIONES)}")
            continue
        await funcion()


if __name__ == "__main__":
    asyncio.run(main())
