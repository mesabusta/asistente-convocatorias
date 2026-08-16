"""Demostración de dos flujos completos (sin Ollama) para evidencia de la wiki."""

from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage

from energia.graph import run_agent
from energia.scripted_llm import ScriptedLLM


async def flujo_demanda() -> str:
    llm = ScriptedLLM(
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
                    "La demanda media de la primera semana de agosto 2019 se obtuvo "
                    "con consultar_demanda y se usa a continuación para el informe."
                )
            ),
        ]
    )
    print("=" * 70)
    print("FLUJO 1 — consultar_demanda (MCP)")
    print("Entrada: ¿Cuál fue la demanda media entre 2019-08-01 y 2019-08-07?")
    print("Decisión: invocar consultar_demanda")
    answer = await run_agent(
        "¿Cuál fue la demanda media entre 2019-08-01 y 2019-08-07?",
        llm,
    )
    print(f"Respuesta final: {answer}")
    return answer


async def flujo_error_luego_picos() -> str:
    llm = ScriptedLLM(
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
                    "El primer intervalo no existe en el dataset; tras el error "
                    "consulté 2019-08-01 a 2019-08-03 y reporto los picos reales."
                )
            ),
        ]
    )
    print("=" * 70)
    print("FLUJO 2 — error de detectar_picos y reintento")
    print("Entrada: picos en 2015 (fuera de rango) y luego intervalo válido")
    answer = await run_agent(
        "Dame los 3 picos de demanda del 1 al 2 de enero de 2015. Si falla, usa agosto 2019.",
        llm,
    )
    print(f"Respuesta final: {answer}")
    return answer


async def main() -> None:
    await flujo_demanda()
    print()
    await flujo_error_luego_picos()


if __name__ == "__main__":
    asyncio.run(main())
