"""Servidor MCP del asistente de convocatorias (transporte stdio).

Expone las tres herramientas de ``centro.tools`` con el mismo patrón del
tutorial del curso: cada función registrada con ``@mcp.tool()`` delega en la
implementación del módulo de tools, de modo que los tests ejerciten la misma
lógica sin levantar el servidor y el servidor no pueda divergir de lo probado.

Ejecución directa (los clientes MCP lo lanzan como subproceso):

    python -m centro.mcp_server
"""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from centro import tools as _t

mcp = FastMCP(
    name="centro-convocatorias-server",
    instructions=(
        "Servidor MCP del Centro de Proyectos y Consultoría de la Universidad de los "
        "Alpes. Expone la consulta pública de convocatorias, la autenticación con rol "
        "y la creación de solicitudes de postulación. Las herramientas internas "
        "verifican el rol por su cuenta: un token sin rol 'personal' no puede crear "
        "solicitudes."
    ),
)


@mcp.tool()
def consultar_convocatoria(
    consulta: Annotated[
        str,
        Field(description="Identificador (p.ej. BID-2026-EDU-014) o texto libre a buscar"),
    ],
) -> str:
    """Encuentra una convocatoria abierta y devuelve sus bases. Información pública."""
    return _t.consultar_convocatoria(consulta)


@mcp.tool()
def autenticar(
    cedula: Annotated[str, Field(description="Número de cédula del miembro del Centro")],
    clave: Annotated[str, Field(description="Clave numérica de 4 dígitos")],
) -> str:
    """Valida credenciales y abre una sesión con rol. Devuelve token y perfil propio."""
    return _t.autenticar(cedula, clave)


@mcp.tool()
def crear_solicitud(
    token: Annotated[str, Field(description="Token de sesión devuelto por autenticar")],
    convocatoria_id: Annotated[str, Field(description="Identificador de la convocatoria")],
    rol_propuesto: Annotated[
        str, Field(description="Rol al que se postula, p.ej. 'investigador principal'")
    ],
    justificacion: Annotated[
        str, Field(description="Por qué su perfil encaja con los requisitos de la convocatoria")
    ],
) -> str:
    """Crea una solicitud de postulación. Exclusiva del personal; valida brechas antes."""
    return _t.crear_solicitud(token, convocatoria_id, rol_propuesto, justificacion)


if __name__ == "__main__":
    mcp.run(transport="stdio")
