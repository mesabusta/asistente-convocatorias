"""Suite de la entrega de semana 2.

Cubre los criterios de éxito del caso de negocio:

- La información pública se responde sin autenticación.
- El control de rol se cumple: el personal no ve datos ajenos ni asigna.
- Las brechas se reportan de forma específica y bloquean la creación de la
  solicitud (overhead, riesgo reputacional).
- La creación de solicitud queda atribuida a quien se autenticó.
- La asignación exige rol directivo y justificación explícita.
- El escalamiento entrega un resumen estructurado.
- El servidor MCP expone las diez herramientas y el agente completa los flujos.

Nota sobre la autenticación: las credenciales de `datos_internos/personal.json`
son datos sintéticos de un caso de estudio. No representan personas reales.
"""

import json

import pytest
from langchain_core.messages import AIMessage

from centro import internos
from centro import tools as t
from centro.graph import run_agent, run_agent_estado, server_config
from centro.scripted_llm import ScriptedLLM

pytestmark = pytest.mark.semana2

CEDULA_PERSONAL = "1030456789"  # Carolina Pérez
CLAVE_PERSONAL = "2964"
CEDULA_DIRECTIVO = "1010234567"  # Luisa Ruiz
CLAVE_DIRECTIVO = "4821"

CONV_VIABLE = "MINCIENCIAS-2026-CEA-003"
CONV_OVERHEAD = "BID-2026-EDU-014"
CONV_RIESGO = "PETROANDINA-2026-RSE-002"


@pytest.fixture(autouse=True)
def estado_limpio():
    """Cada test parte del mismo estado: sin sesiones, solicitudes sembradas."""
    internos.reiniciar_estado()
    yield
    internos.reiniciar_estado()


def j(salida: str) -> dict:
    return json.loads(salida)


def token_personal() -> str:
    return j(t.autenticar(CEDULA_PERSONAL, CLAVE_PERSONAL))["token"]


def token_directivo() -> str:
    return j(t.autenticar(CEDULA_DIRECTIVO, CLAVE_DIRECTIVO))["token"]


# ==========================================================================
# Información pública — sin autenticación
# ==========================================================================


def test_buscar_convocatorias_sin_autenticar():
    payload = j(t.buscar_convocatorias(area="educacion_superior"))
    assert payload["ok"] is True
    assert payload["fuente"] == "publica"
    assert payload["n_resultados"] >= 1


def test_buscar_convocatorias_sin_resultados_sugiere_areas():
    payload = j(t.buscar_convocatorias(area="astrofisica"))
    assert payload["ok"] is False
    assert payload["areas_disponibles"]


def test_leer_convocatoria_expone_tope_y_minimo_institucional():
    payload = j(t.leer_convocatoria(CONV_OVERHEAD))
    assert payload["ok"] is True
    assert payload["overhead_maximo_pct"] == 12
    assert payload["overhead_minimo_institucional_pct"] == 15
    assert "consorcio" in payload["texto"].lower()


def test_leer_convocatoria_marca_senales_de_riesgo():
    payload = j(t.leer_convocatoria(CONV_RIESGO))
    assert payload["ok"] is True
    assert payload["sector_entidad"] == "extractivo"
    assert len(payload["señales_de_riesgo"]) >= 2


def test_leer_convocatoria_inexistente_lista_ids():
    payload = j(t.leer_convocatoria("NO-EXISTE-001"))
    assert payload["ok"] is False
    assert CONV_VIABLE in payload["ids_disponibles"]


@pytest.mark.parametrize(
    "tema,esperado",
    [
        ("overhead", "POL-FIN-001"),
        ("riesgo reputacional", "POL-RIE-002"),
        ("niveles de autorizacion", "POL-GOB-003"),
        ("conflicto de interes", "POL-ETI-004"),
    ],
)
def test_consultar_politica_encuentra_la_correcta(tema, esperado):
    payload = j(t.consultar_politica(tema))
    assert payload["ok"] is True
    assert payload["id"] == esperado


# ==========================================================================
# Autenticación
# ==========================================================================


def test_autenticar_personal_devuelve_rol_y_capacidades():
    payload = j(t.autenticar(CEDULA_PERSONAL, CLAVE_PERSONAL))
    assert payload["ok"] is True
    assert payload["rol"] == "personal"
    assert "crear_solicitud" in payload["capacidades"]
    assert "asignar_convocatoria" not in payload["capacidades"]


def test_autenticar_directivo_habilita_asignar():
    payload = j(t.autenticar(CEDULA_DIRECTIVO, CLAVE_DIRECTIVO))
    assert payload["rol"] == "directivo"
    assert "asignar_convocatoria" in payload["capacidades"]


def test_autenticar_con_clave_incorrecta_falla():
    payload = j(t.autenticar(CEDULA_PERSONAL, "0000"))
    assert payload["ok"] is False


def test_token_invalido_es_rechazado():
    payload = j(t.consultar_perfil("ses_inventado"))
    assert payload["ok"] is False


# ==========================================================================
# Control de rol — el criterio de éxito más importante
# ==========================================================================


def test_personal_no_puede_listar_personal():
    payload = j(t.listar_personal(token_personal()))
    assert payload["ok"] is False
    assert "directivo" in payload["error"]


def test_personal_no_puede_listar_solicitudes():
    payload = j(t.listar_solicitudes(token_personal()))
    assert payload["ok"] is False


def test_personal_no_puede_asignar():
    payload = j(
        t.asignar_convocatoria(
            token_personal(),
            CONV_VIABLE,
            [CEDULA_PERSONAL],
            "Intento de autoasignación que debe ser rechazado por el control de rol.",
        )
    )
    assert payload["ok"] is False
    assert internos.asignacion_de(CONV_VIABLE) is None


def test_directivo_no_puede_crear_solicitud():
    """La simetría también importa: crear_solicitud es del personal."""
    payload = j(
        t.crear_solicitud(token_directivo(), CONV_VIABLE, "investigadora", "justificación")
    )
    assert payload["ok"] is False


def test_perfil_solo_devuelve_el_propio_y_nunca_la_clave():
    payload = j(t.consultar_perfil(token_personal()))
    assert payload["ok"] is True
    assert payload["perfil"]["cedula"] == CEDULA_PERSONAL
    assert "clave" not in payload["perfil"]


def test_directivo_ve_a_todo_el_personal():
    payload = j(t.listar_personal(token_directivo()))
    assert payload["ok"] is True
    assert payload["n_personas"] == len(internos.personal())
    assert all("clave" not in p for p in payload["personal"])


def test_listar_personal_por_area_inexistente_reporta_brecha():
    payload = j(t.listar_personal(token_directivo(), area="astrofisica"))
    assert payload["ok"] is False
    assert payload["brecha"] == "experticia"


# ==========================================================================
# Brechas — reporte específico, no rechazo genérico
# ==========================================================================


def test_brecha_de_overhead_bloquea_la_solicitud():
    payload = j(
        t.crear_solicitud(token_personal(), CONV_OVERHEAD, "investigadora principal", "encajo")
    )
    assert payload["ok"] is False
    assert payload["brecha"] == "overhead"
    assert payload["overhead_convocatoria_pct"] == 12
    assert payload["overhead_minimo_institucional_pct"] == 15
    assert not internos.existe_solicitud(CONV_OVERHEAD, CEDULA_PERSONAL)


def test_riesgo_reputacional_bloquea_la_solicitud():
    payload = j(t.crear_solicitud(token_personal(), CONV_RIESGO, "consultora", "el tema encaja"))
    assert payload["ok"] is False
    assert payload["brecha"] == "riesgo_reputacional"
    assert payload["requiere_escalamiento"] is True


def test_riesgo_reputacional_bloquea_la_asignacion():
    payload = j(
        t.asignar_convocatoria(
            token_directivo(),
            CONV_RIESGO,
            [CEDULA_PERSONAL],
            "Justificación suficientemente larga para pasar la validación de longitud.",
        )
    )
    assert payload["ok"] is False
    assert payload["brecha"] == "riesgo_reputacional"
    assert internos.asignacion_de(CONV_RIESGO) is None


# ==========================================================================
# Acciones — solicitud y asignación
# ==========================================================================


def test_crear_solicitud_duplicada_es_rechazada():
    antes = len(internos.solicitudes_de(CONV_VIABLE))
    payload = j(
        t.crear_solicitud(
            token_personal(),
            CONV_VIABLE,
            "investigadora principal",
            "5 publicaciones recientes y dedicación de tiempo completo.",
        )
    )
    # Carolina ya está sembrada en solicitudes.json: la segunda vez es duplicada.
    assert payload["ok"] is False
    assert payload["brecha"] == "duplicada"
    assert len(internos.solicitudes_de(CONV_VIABLE)) == antes


def test_crear_solicitud_nueva_se_registra():
    token = j(t.autenticar("1080901234", "3846"))["token"]  # Ricardo Tovar
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
    assert internos.existe_solicitud(CONV_VIABLE, "1080901234")


def test_asignar_exige_justificacion():
    payload = j(
        t.asignar_convocatoria(token_directivo(), CONV_VIABLE, [CEDULA_PERSONAL], "corta")
    )
    assert payload["ok"] is False
    assert internos.asignacion_de(CONV_VIABLE) is None


def test_asignar_rechaza_cedulas_desconocidas():
    payload = j(
        t.asignar_convocatoria(
            token_directivo(),
            CONV_VIABLE,
            ["0000000000"],
            "Justificación suficientemente larga para pasar la validación de longitud.",
        )
    )
    assert payload["ok"] is False
    assert payload["brecha"] == "persona_inexistente"


def test_asignar_actualiza_el_estado_de_las_solicitudes():
    payload = j(
        t.asignar_convocatoria(
            token_directivo(),
            CONV_VIABLE,
            [CEDULA_PERSONAL, "1060789012"],
            "Carolina cumple el requisito de investigadora principal con 5 publicaciones y "
            "tiempo completo; Sebastián aporta la maestría exigida al investigador de apoyo.",
        )
    )
    assert payload["ok"] is True
    estados = {s["nombre"]: s["estado"] for s in internos.solicitudes_de(CONV_VIABLE)}
    assert estados["Carolina Pérez"] == "asignada"
    assert estados["Sebastián Cruz"] == "asignada"
    assert estados["Felipe Manrique"] == "no_seleccionada"


# ==========================================================================
# Escalamiento
# ==========================================================================


def test_escalar_entrega_resumen_estructurado():
    payload = j(
        t.escalar_a_humanos(
            motivo="Riesgo reputacional del sector extractivo.",
            convocatoria_id=CONV_RIESGO,
            analisis_realizado=["Leí las bases y la política POL-RIE-002."],
            brechas=["Sector con restricción.", "Datos sensibles de comunidades."],
            preguntas_pendientes=["¿El Comité emite concepto favorable?"],
        )
    )
    assert payload["ok"] is True
    assert payload["destinatario"] == "Comité de Ética y Reputación"
    assert len(payload["brechas"]) == 2
    assert payload["preguntas_pendientes"]


def test_escalar_exige_motivo():
    payload = j(t.escalar_a_humanos(motivo="  "))
    assert payload["ok"] is False


# ==========================================================================
# Integración MCP y flujos agénticos
# ==========================================================================


@pytest.mark.asyncio
async def test_mcp_expone_las_diez_herramientas():
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient(server_config())
    async with client.session("centro") as session:
        raw = await session.list_tools()
        nombres = {tool.name for tool in raw.tools}
    esperadas = {
        "buscar_convocatorias",
        "leer_convocatoria",
        "consultar_politica",
        "autenticar",
        "consultar_perfil",
        "listar_personal",
        "listar_solicitudes",
        "crear_solicitud",
        "asignar_convocatoria",
        "escalar_a_humanos",
    }
    assert esperadas <= nombres


@pytest.mark.asyncio
async def test_flujo_consulta_publica_no_pide_identidad():
    llm = ScriptedLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "leer_convocatoria",
                        "args": {"convocatoria_id": CONV_OVERHEAD},
                        "id": "p1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="La convocatoria reconoce overhead máximo del 12%."),
        ]
    )
    estado = await run_agent_estado("¿Qué pide la convocatoria del BID?", llm)
    herramientas_usadas = [
        c["name"]
        for m in estado["messages"]
        for c in (getattr(m, "tool_calls", None) or [])
    ]
    assert "autenticar" not in herramientas_usadas
    assert "12%" in estado["messages"][-1].content


@pytest.mark.asyncio
async def test_flujo_personal_crea_solicitud_via_mcp():
    llm = ScriptedLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "autenticar",
                        "args": {"cedula": "1080901234", "clave": "3846"},
                        "id": "f1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "crear_solicitud",
                        "args": {
                            "token": "<TOKEN>",
                            "convocatoria_id": CONV_VIABLE,
                            "rol_propuesto": "investigador principal",
                            "justificacion": "Cumple publicaciones y dedicación.",
                        },
                        "id": "f2",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Solicitud creada; la asignación la decide la Dirección."),
        ]
    )
    estado = await run_agent_estado("¿Puedo aplicar a la de Minciencias?", llm)
    resultados = [
        json.loads(m.content)
        for m in estado["messages"]
        if m.__class__.__name__ == "ToolMessage"
    ]
    assert resultados[-1]["ok"] is True
    assert resultados[-1]["accion"] == "solicitud_creada"


@pytest.mark.asyncio
async def test_flujo_personal_que_intenta_asignar_es_rechazado_por_la_tool():
    """El control de rol no depende del prompt: aunque el modelo lo intente, falla."""
    llm = ScriptedLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "autenticar",
                        "args": {"cedula": CEDULA_PERSONAL, "clave": CLAVE_PERSONAL},
                        "id": "r1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "asignar_convocatoria",
                        "args": {
                            "token": "<TOKEN>",
                            "convocatoria_id": CONV_VIABLE,
                            "cedulas": [CEDULA_PERSONAL],
                            "justificacion": "Me asigno a mí misma porque cumplo el perfil.",
                        },
                        "id": "r2",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="No puedo asignarte: esa decisión es de la Dirección."),
        ]
    )
    estado = await run_agent_estado("Asígname a la convocatoria de Minciencias", llm)
    ultimo = json.loads(
        [m for m in estado["messages"] if m.__class__.__name__ == "ToolMessage"][-1].content
    )
    assert ultimo["ok"] is False
    assert "directivo" in ultimo["error"]


@pytest.mark.asyncio
async def test_flujo_riesgo_reputacional_escala():
    llm = ScriptedLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "leer_convocatoria",
                        "args": {"convocatoria_id": CONV_RIESGO},
                        "id": "e1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "escalar_a_humanos",
                        "args": {
                            "motivo": "Sector extractivo con datos sensibles de comunidades.",
                            "convocatoria_id": CONV_RIESGO,
                            "brechas": ["Sector con restricción reputacional."],
                            "preguntas_pendientes": ["¿Concepto del Comité?"],
                        },
                        "id": "e2",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Escalé el caso al Comité de Ética y Reputación."),
        ]
    )
    respuesta = await run_agent("¿Aplicamos a la de la petrolera?", llm)
    assert "escal" in respuesta.lower()
