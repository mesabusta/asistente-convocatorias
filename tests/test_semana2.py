import json

import pytest
from langchain_core.messages import AIMessage

from energia.graph import run_agent, server_config
from energia.scripted_llm import ScriptedLLM
from energia.tools import consultar_demanda, consultar_pronostico, detectar_picos

pytestmark = pytest.mark.semana2


def test_consultar_demanda_ok():
    payload = json.loads(consultar_demanda("2019-08-01", "2019-08-07"))
    assert payload["ok"] is True
    assert payload["n_hours"] > 0
    assert payload["mean_mw"] > 0


def test_consultar_demanda_error_fuera_de_rango():
    payload = json.loads(consultar_demanda("2015-01-01", "2015-01-02"))
    assert payload["ok"] is False
    assert "error" in payload


def test_consultar_demanda_error_fechas_invertidas():
    payload = json.loads(consultar_demanda("2019-08-10", "2019-08-01"))
    assert payload["ok"] is False


def test_detectar_picos_ok():
    payload = json.loads(detectar_picos("2019-08-01", "2019-08-03", n=3))
    assert payload["ok"] is True
    assert len(payload["peaks"]) == 3
    mws = [p["mw"] for p in payload["peaks"]]
    assert mws == sorted(mws, reverse=True)


def test_detectar_picos_n_invalido():
    payload = json.loads(detectar_picos("2019-08-01", "2019-08-03", n=99))
    assert payload["ok"] is False


def test_consultar_pronostico_ok():
    payload = json.loads(consultar_pronostico("2020-10-01", "2020-10-06"))
    assert payload["ok"] is True
    assert payload["n_forecast_hours"] > 0


@pytest.mark.asyncio
async def test_mcp_session_lista_tools():
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient(server_config())
    async with client.session("energia") as session:
        raw = await session.list_tools()
        names = {t.name for t in raw.tools}
    assert {"consultar_demanda", "consultar_pronostico", "detectar_picos"} <= names


@pytest.mark.asyncio
async def test_flujo_consultar_demanda_via_mcp():
    llm = ScriptedLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "consultar_demanda",
                        "args": {"start": "2019-08-01", "end": "2019-08-07"},
                        "id": "t1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Demanda media obtenida desde MCP."),
        ]
    )
    answer = await run_agent("Demanda media 1-7 agosto 2019", llm)
    assert "MCP" in answer or "demanda" in answer.lower()


@pytest.mark.asyncio
async def test_flujo_error_y_reintento_picos():
    llm = ScriptedLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "detectar_picos",
                        "args": {"start": "2015-01-01", "end": "2015-01-02", "n": 3},
                        "id": "t-err",
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
                        "id": "t-ok",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Tras el error, reporto los picos de agosto 2019."),
        ]
    )
    answer = await run_agent("Picos en 2015; si falla usa agosto 2019", llm)
    assert "picos" in answer.lower() or "agosto" in answer.lower()
