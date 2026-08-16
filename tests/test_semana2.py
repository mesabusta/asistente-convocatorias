"""Suite de la entrega de semana 2.

Cubre lo que exige la rúbrica y los criterios del caso de negocio:

- La información pública se responde sin autenticación.
- La autenticación valida credenciales y nunca expone la clave.
- El control de rol vive en la herramienta, no en el prompt: un directivo no
  puede crear solicitudes.
- Las brechas se reportan de forma específica (overhead, riesgo reputacional,
  duplicada) y bloquean la creación de la solicitud.
- La creación de solicitud queda atribuida a quien se autenticó.
- El servidor MCP expone las tres herramientas y el agente completa los flujos
  extremo a extremo, incluido el manejo de un error.

Nota: las credenciales de `datos_internos/personal.json` son datos sintéticos
de un caso de estudio. No representan personas reales.
"""

import json

import pytest
from langchain_core.messages import AIMessage

from centro import tools as t
from centro.graph import run_agent_estado
from centro.scripted_llm import ScriptedLLM

pytestmark = pytest.mark.semana2

CEDULA_PERSONAL = "1030456789"  # Carolina Pérez
CLAVE_PERSONAL = "2964"
CEDULA_DIRECTIVO = "1010234567"  # Luisa Ruiz
CLAVE_DIRECTIVO = "4821"
CEDULA_NUEVO = "1080901234"  # Ricardo Tovar (sin solicitudes sembradas)
CLAVE_NUEVO = "3846"

CONV_VIABLE = "MINCIENCIAS-2026-CEA-003"
CONV_OVERHEAD = "BID-2026-EDU-014"
CONV_RIESGO = "PETROANDINA-2026-RSE-002"


@pytest.fixture(autouse=True)
def estado_limpio():
    """Cada test parte del mismo estado: sin sesiones, solicitudes sembradas."""
    t.reiniciar_estado()
    yield
    t.reiniciar_estado()


def j(salida: str) -> dict:
    return json.loads(salida)


def token_de(cedula: str, clave: str) -> str:
    return j(t.autenticar(cedula, clave))["token"]


def _llamada(nombre: str, args: dict, id_: str) -> dict:
    return {"name": nombre, "args": args, "id": id_, "type": "tool_call"}


# ==========================================================================
# Tool 1 — consultar_convocatoria (pública)
# ==========================================================================


def test_consultar_por_id_devuelve_bases_sin_autenticar():
    payload = j(t.consultar_convocatoria(CONV_OVERHEAD))
    assert payload["ok"] is True
    assert payload["fuente"] == "publica"
    assert payload["overhead_maximo_pct"] == 12
    assert payload["overhead_minimo_institucional_pct"] == 15
    assert "consorcio" in payload["texto"].lower()


def test_consultar_por_texto_encuentra_la_convocatoria():
    payload = j(t.consultar_convocatoria("Minciencias"))
    assert payload["ok"] is True
    assert payload["id"] == CONV_VIABLE


def test_consultar_marca_senales_de_riesgo():
    payload = j(t.consultar_convocatoria(CONV_RIESGO))
    assert payload["ok"] is True
    assert payload["señales_de_riesgo"]


def test_consultar_inexistente_lista_ids_disponibles():
    payload = j(t.consultar_convocatoria("astrofisica cuantica"))
    assert payload["ok"] is False
    assert CONV_VIABLE in payload["ids_disponibles"]


# ==========================================================================
# Tool 2 — autenticar
# ==========================================================================


def test_autenticar_devuelve_rol_y_perfil_sin_clave():
    payload = j(t.autenticar(CEDULA_PERSONAL, CLAVE_PERSONAL))
    assert payload["ok"] is True
    assert payload["rol"] == "personal"
    assert payload["perfil"]["cedula"] == CEDULA_PERSONAL
    assert "clave" not in payload["perfil"]


def test_autenticar_con_clave_incorrecta_falla():
    payload = j(t.autenticar(CEDULA_PERSONAL, "0000"))
    assert payload["ok"] is False


# ==========================================================================
# Tool 3 — crear_solicitud: rol, brechas y registro
# ==========================================================================


def test_token_invalido_es_rechazado():
    payload = j(t.crear_solicitud("ses_inventado", CONV_VIABLE, "investigadora", "encajo"))
    assert payload["ok"] is False


def test_directivo_no_puede_crear_solicitud():
    """El control de rol vive en la tool: crear solicitudes es del personal."""
    token = token_de(CEDULA_DIRECTIVO, CLAVE_DIRECTIVO)
    payload = j(t.crear_solicitud(token, CONV_VIABLE, "investigadora", "justificación"))
    assert payload["ok"] is False
    assert "personal" in payload["error"]


def test_brecha_de_overhead_bloquea_la_solicitud():
    token = token_de(CEDULA_PERSONAL, CLAVE_PERSONAL)
    payload = j(t.crear_solicitud(token, CONV_OVERHEAD, "investigadora principal", "encajo"))
    assert payload["ok"] is False
    assert payload["brecha"] == "overhead"
    assert payload["overhead_convocatoria_pct"] == 12
    assert payload["overhead_minimo_institucional_pct"] == 15
    assert not any(s["cedula"] == CEDULA_PERSONAL for s in t.solicitudes_de(CONV_OVERHEAD))


def test_riesgo_reputacional_bloquea_la_solicitud():
    token = token_de(CEDULA_PERSONAL, CLAVE_PERSONAL)
    payload = j(t.crear_solicitud(token, CONV_RIESGO, "consultora", "el tema encaja"))
    assert payload["ok"] is False
    assert payload["brecha"] == "riesgo_reputacional"


def test_solicitud_duplicada_es_rechazada():
    # Carolina ya está sembrada en solicitudes.json para esta convocatoria.
    antes = len(t.solicitudes_de(CONV_VIABLE))
    token = token_de(CEDULA_PERSONAL, CLAVE_PERSONAL)
    payload = j(t.crear_solicitud(token, CONV_VIABLE, "investigadora principal", "5 publicaciones"))
    assert payload["ok"] is False
    assert payload["brecha"] == "duplicada"
    assert len(t.solicitudes_de(CONV_VIABLE)) == antes


def test_crear_solicitud_nueva_queda_atribuida_al_autenticado():
    token = token_de(CEDULA_NUEVO, CLAVE_NUEVO)
    payload = j(
        t.crear_solicitud(
            token,
            CONV_VIABLE,
            "investigador principal",
            "7 publicaciones recientes y dedicación de tiempo completo.",
        )
    )
    assert payload["ok"] is True
    assert payload["accion"] == "solicitud_creada"
    assert payload["solicitud"]["nombre"] == "Ricardo Tovar"
    assert payload["solicitud"]["estado"] == "pendiente"


# ==========================================================================
# Integración MCP y flujos agénticos (servidor real por stdio, LLM guionizado)
# ==========================================================================


@pytest.mark.asyncio
async def test_mcp_expone_las_tres_herramientas():
    from langchain_mcp_adapters.client import MultiServerMCPClient

    from centro.graph import server_config

    client = MultiServerMCPClient(server_config())
    async with client.session("centro") as session:
        raw = await session.list_tools()
        nombres = {tool.name for tool in raw.tools}
    assert {"consultar_convocatoria", "autenticar", "crear_solicitud"} <= nombres


@pytest.mark.asyncio
async def test_flujo_consulta_publica_no_pide_identidad():
    llm = ScriptedLLM(
        [
            AIMessage(
                content="",
                tool_calls=[_llamada("consultar_convocatoria", {"consulta": CONV_OVERHEAD}, "p1")],
            ),
            AIMessage(content="La convocatoria reconoce overhead máximo del 12%."),
        ]
    )
    estado = await run_agent_estado("¿Qué pide la convocatoria del BID?", llm)
    herramientas_usadas = [
        c["name"] for m in estado["messages"] for c in (getattr(m, "tool_calls", None) or [])
    ]
    assert "autenticar" not in herramientas_usadas
    assert "12%" in estado["messages"][-1].content


@pytest.mark.asyncio
async def test_flujo_postulacion_crea_solicitud_via_mcp():
    llm = ScriptedLLM(
        [
            AIMessage(
                content="",
                tool_calls=[_llamada("autenticar", {"cedula": CEDULA_NUEVO, "clave": CLAVE_NUEVO}, "f1")],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    _llamada(
                        "crear_solicitud",
                        {
                            "token": "<TOKEN>",
                            "convocatoria_id": CONV_VIABLE,
                            "rol_propuesto": "investigador principal",
                            "justificacion": "Cumple publicaciones y dedicación.",
                        },
                        "f2",
                    )
                ],
            ),
            AIMessage(content="Solicitud creada; la asignación la decide la Dirección."),
        ]
    )
    estado = await run_agent_estado("¿Puedo aplicar a la de Minciencias?", llm)
    resultados = [
        json.loads(m.content) for m in estado["messages"] if m.__class__.__name__ == "ToolMessage"
    ]
    assert resultados[-1]["ok"] is True
    assert resultados[-1]["accion"] == "solicitud_creada"


@pytest.mark.asyncio
async def test_flujo_con_error_reporta_brecha_y_no_crea_nada():
    """Manejo explícito de un resultado inesperado: ok=false con brecha."""
    llm = ScriptedLLM(
        [
            AIMessage(
                content="",
                tool_calls=[_llamada("autenticar", {"cedula": CEDULA_PERSONAL, "clave": CLAVE_PERSONAL}, "e1")],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    _llamada(
                        "crear_solicitud",
                        {
                            "token": "<TOKEN>",
                            "convocatoria_id": CONV_OVERHEAD,
                            "rol_propuesto": "investigadora principal",
                            "justificacion": "Mi experticia encaja con el objeto.",
                        },
                        "e2",
                    )
                ],
            ),
            AIMessage(content="No creé la solicitud: hay una brecha de overhead (12% < 15%)."),
        ]
    )
    estado = await run_agent_estado("Créame la solicitud para la del BID.", llm)
    ultimo = json.loads(
        [m for m in estado["messages"] if m.__class__.__name__ == "ToolMessage"][-1].content
    )
    assert ultimo["ok"] is False
    assert ultimo["brecha"] == "overhead"
    assert "brecha" in estado["messages"][-1].content.lower()


@pytest.mark.asyncio
async def test_herramienta_desconocida_devuelve_error_controlado():
    """El nodo de tools convierte una llamada alucinada en un error legible."""
    llm = ScriptedLLM(
        [
            AIMessage(
                content="",
                tool_calls=[_llamada("asignar_convocatoria", {"convocatoria_id": CONV_VIABLE}, "x1")],
            ),
            AIMessage(content="Esa acción no está disponible en este asistente."),
        ]
    )
    estado = await run_agent_estado("Asígname a la convocatoria de Minciencias", llm)
    ultimo = [m for m in estado["messages"] if m.__class__.__name__ == "ToolMessage"][-1]
    payload = json.loads(ultimo.content)
    assert payload["ok"] is False
    assert "desconocida" in payload["error"].lower()
