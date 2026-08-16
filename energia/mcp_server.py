"""Servidor MCP del caso de demanda energética (stdio)."""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from energia.tools import consultar_demanda as _consultar_demanda
from energia.tools import consultar_pronostico as _consultar_pronostico
from energia.tools import detectar_picos as _detectar_picos

mcp = FastMCP(
    name="energia-demanda-server",
    instructions=(
        "Servidor MCP del analista de demanda energética en Austria (ENTSO-E). "
        "Expone estadísticas de demanda, evaluación de pronóstico y detección de picos."
    ),
)


@mcp.tool()
def consultar_demanda(
    start: Annotated[str, Field(description="Fecha/hora inicial ISO, p.ej. 2019-08-01")],
    end: Annotated[str, Field(description="Fecha/hora final ISO, p.ej. 2019-08-07")],
) -> str:
    """Estadísticas de demanda real (MW) en un intervalo horario."""
    return _consultar_demanda(start, end)


@mcp.tool()
def consultar_pronostico(
    start: Annotated[str, Field(description="Fecha/hora inicial ISO del tramo a evaluar")],
    end: Annotated[str, Field(description="Fecha/hora final ISO del tramo a evaluar")],
) -> str:
    """Compara pronóstico vs demanda real y reporta MAE cuando ambos existen."""
    return _consultar_pronostico(start, end)


@mcp.tool()
def detectar_picos(
    start: Annotated[str, Field(description="Fecha/hora inicial ISO")],
    end: Annotated[str, Field(description="Fecha/hora final ISO")],
    n: Annotated[int, Field(description="Cantidad de picos a devolver (1 a 24)")] = 5,
) -> str:
    """Devuelve las n horas de mayor demanda real en el intervalo."""
    return _detectar_picos(start, end, n)


if __name__ == "__main__":
    mcp.run(transport="stdio")
