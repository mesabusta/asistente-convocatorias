"""Servidor MCP del asistente de convocatorias (transporte stdio).

Expone las diez herramientas de `centro.tools`. La lógica no se duplica: cada
función registrada con `@mcp.tool()` delega en la implementación del módulo de
tools, de modo que los tests puedan ejercitar la misma lógica sin levantar el
servidor y el servidor no pueda divergir de lo que se prueba.
"""

from typing import Annotated, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from centro import tools as _t

mcp = FastMCP(
    name="centro-convocatorias-server",
    instructions=(
        "Servidor MCP del Centro de Proyectos y Consultoría de la Universidad de los Alpes. "
        "Expone la base de conocimiento pública (convocatorias y políticas de participación), "
        "autenticación con rol, y las acciones internas de crear solicitud, asignar "
        "convocatoria y escalar al equipo humano. Las herramientas internas verifican el rol "
        "por su cuenta: un token de personal no puede ejecutar acciones de directivo."
    ),
)


# -------------------- Públicas --------------------


@mcp.tool()
def buscar_convocatorias(
    area: Annotated[
        Optional[str],
        Field(description="Área temática: educacion_superior, politica_publica, sostenibilidad, desarrollo_economico"),
    ] = None,
    tipo: Annotated[
        Optional[str],
        Field(description="Tipo: investigacion, consultoria, cooperacion_tecnica, formacion, impacto_social"),
    ] = None,
    texto: Annotated[
        Optional[str], Field(description="Texto libre a buscar en el contenido de la convocatoria")
    ] = None,
) -> str:
    """Lista las convocatorias abiertas. Información pública, sin autenticación."""
    return _t.buscar_convocatorias(area, tipo, texto)


@mcp.tool()
def leer_convocatoria(
    convocatoria_id: Annotated[
        str, Field(description="Identificador de la convocatoria, p.ej. BID-2026-EDU-014")
    ],
) -> str:
    """Lee las bases completas de una convocatoria. Información pública."""
    return _t.leer_convocatoria(convocatoria_id)


@mcp.tool()
def consultar_politica(
    tema: Annotated[
        str,
        Field(description="Tema de la política: overhead, contrapartida, riesgo reputacional, autorización, conflicto de interés"),
    ],
) -> str:
    """Lee una política de participación de la universidad. Información pública."""
    return _t.consultar_politica(tema)


# -------------------- Frontera --------------------


@mcp.tool()
def autenticar(
    cedula: Annotated[str, Field(description="Número de cédula del miembro del Centro")],
    clave: Annotated[str, Field(description="Clave numérica de 4 dígitos")],
) -> str:
    """Valida credenciales y abre una sesión con rol (personal o directivo)."""
    return _t.autenticar(cedula, clave)


# -------------------- Lectura interna --------------------


@mcp.tool()
def consultar_perfil(
    token: Annotated[str, Field(description="Token de sesión devuelto por autenticar")],
) -> str:
    """Devuelve el perfil del usuario autenticado. Solo el propio, nunca el de otro."""
    return _t.consultar_perfil(token)


@mcp.tool()
def listar_personal(
    token: Annotated[str, Field(description="Token de sesión de un directivo")],
    area: Annotated[Optional[str], Field(description="Filtra por área de experticia")] = None,
) -> str:
    """Lista a todo el personal del Centro. Exclusiva de directivos."""
    return _t.listar_personal(token, area)


@mcp.tool()
def listar_solicitudes(
    token: Annotated[str, Field(description="Token de sesión de un directivo")],
    convocatoria_id: Annotated[
        Optional[str], Field(description="Filtra por convocatoria; si se omite, devuelve todas")
    ] = None,
) -> str:
    """Lista las solicitudes creadas por el personal. Exclusiva de directivos."""
    return _t.listar_solicitudes(token, convocatoria_id)


# -------------------- Acciones --------------------


@mcp.tool()
def crear_solicitud(
    token: Annotated[str, Field(description="Token de sesión de un miembro del personal")],
    convocatoria_id: Annotated[str, Field(description="Identificador de la convocatoria")],
    rol_propuesto: Annotated[
        str, Field(description="Rol al que se postula, p.ej. 'investigador principal'")
    ],
    justificacion: Annotated[
        str, Field(description="Por qué su perfil encaja con los requisitos de la convocatoria")
    ],
) -> str:
    """Crea una solicitud de postulación. Exclusiva del personal; verifica brechas antes."""
    return _t.crear_solicitud(token, convocatoria_id, rol_propuesto, justificacion)


@mcp.tool()
def asignar_convocatoria(
    token: Annotated[str, Field(description="Token de sesión de un directivo")],
    convocatoria_id: Annotated[str, Field(description="Identificador de la convocatoria")],
    cedulas: Annotated[
        list[str], Field(description="Cédulas del personal que conformará el equipo")
    ],
    justificacion: Annotated[
        str, Field(description="Por qué ese equipo, contra los criterios de evaluación")
    ],
) -> str:
    """Asigna la convocatoria a un equipo. Exclusiva de directivos; exige justificación."""
    return _t.asignar_convocatoria(token, convocatoria_id, cedulas, justificacion)


@mcp.tool()
def escalar_a_humanos(
    motivo: Annotated[str, Field(description="Por qué el caso supera la capacidad del asistente")],
    convocatoria_id: Annotated[
        Optional[str], Field(description="Convocatoria involucrada, si aplica")
    ] = None,
    analisis_realizado: Annotated[
        Optional[list[str]], Field(description="Qué alcanzó a verificar el asistente")
    ] = None,
    brechas: Annotated[
        Optional[list[str]], Field(description="Brechas o riesgos que no pudo resolver")
    ] = None,
    preguntas_pendientes: Annotated[
        Optional[list[str]], Field(description="Preguntas concretas que requieren juicio humano")
    ] = None,
) -> str:
    """Escala el caso al equipo humano con un resumen estructurado de lo evaluado."""
    return _t.escalar_a_humanos(
        motivo, convocatoria_id, analisis_realizado, brechas, preguntas_pendientes
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
