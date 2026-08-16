# Agente de demanda energética

Agente conversacional que responde preguntas sobre la demanda eléctrica de Austria
consultando el dataset de ENTSO-E a través de herramientas expuestas por un
servidor **MCP** (Model Context Protocol), más un dashboard de visualización.

**Integrantes:** [mesabusta](https://github.com/mesabusta) · [ysusecheo93](https://github.com/ysusecheo93)

---

## Qué hace

El agente no razona sobre los datos crudos: decide **qué herramienta invocar**,
la ejecuta contra el servidor MCP y redacta la respuesta sobre las cifras que
recibe. Si el intervalo pedido no existe en el dataset, la herramienta devuelve
un error estructurado y el agente reintenta con un rango válido en lugar de
inventar números.

### Herramientas expuestas

| Tool | Qué devuelve |
|---|---|
| `consultar_demanda` | Horas observadas, media, mínimo y máximo de MW en un intervalo |
| `consultar_pronostico` | Resumen del pronóstico y MAE contra la demanda real cuando hay pares |
| `detectar_picos` | Las *n* horas de mayor carga del intervalo (1 ≤ n ≤ 24) |

Las tres viven en `energia/tools.py` y se exponen vía `energia/mcp_server.py`.
El cliente las descubre en tiempo de ejecución con `load_mcp_tools()`: **no hay
herramientas locales declaradas en el grafo**, así que agregar una tool al
servidor no requiere tocar el agente.

---

## Arquitectura

```
Usuario
  │
  ▼
┌─────────────────────────────────────────┐
│  Cliente LangGraph  (energia/graph.py)  │
│                                         │
│   agent_node ──► should_continue        │
│       ▲               │                 │
│       │               ▼                 │
│       └────────── tools_node            │
└───────────────────────┬─────────────────┘
                        │  JSON-RPC sobre stdio (MCP)
                        ▼
┌─────────────────────────────────────────┐
│  Servidor FastMCP (energia/mcp_server)  │
│  consultar_demanda │ consultar_pronostico│
│           detectar_picos                │
└───────────────────────┬─────────────────┘
                        ▼
                datos_energia.csv
```

El agente es *stateful*: el historial completo de mensajes viaja en el estado
del grafo (`AgentState.messages` con `add_messages`), lo que permite encadenar
varias llamadas a herramientas antes de responder.

---

## Estructura

```
energia/
  tools.py           Las tres herramientas (lógica de negocio)
  mcp_server.py      Servidor FastMCP sobre stdio
  graph.py           Cliente LangGraph, ciclo ReAct y descubrimiento dinámico
  data.py            Carga y rebanado del CSV
  scripted_llm.py    LLM determinista para tests y demos sin Ollama
  demo_flujos.py     Demo resumida de dos flujos completos
  evidencia_flujo.py Traza detallada: decisión, argumentos, resultado MCP y respuesta
tests/
  test_semana2.py    9 tests: tools, errores, handshake MCP y flujos agénticos
app.py               Dashboard de visualización (Dash)
datos_energia.csv    Serie horaria ENTSO-E de Austria
wiki_semana2.md      Documento de reflexión de la semana 2
```

Los notebooks (`tool_calling`, `servidor_mcp`, `cliente_mcp`,
`agente_entrevista`) recorren los conceptos paso a paso y requieren Ollama con
`qwen2.5:3b`.

---

## Instalación

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

En Linux o macOS: `python3 -m venv .venv && source .venv/bin/activate`.

---

## Uso

**Demo de dos flujos completos** (no requiere Ollama):

```powershell
python -m energia.demo_flujos
```

**Traza detallada** — muestra la decisión del agente, los argumentos elegidos,
el JSON que devuelve el servidor MCP y la respuesta final:

```powershell
python -m energia.evidencia_flujo
```

**Tests:**

```powershell
pytest -m semana2 -q
```

**Dashboard:**

```powershell
python app.py
```

---

## Datos

`datos_energia.csv` contiene la serie horaria de carga de Austria publicada por
ENTSO-E. El rango disponible va del **2019-07-25 17:00** al **2020-10-06 01:00**;
cualquier consulta fuera de esa ventana devuelve un error estructurado con el
rango válido incluido en el mensaje.

Columnas relevantes:

- `AT_load_actual_entsoe_transparency` — demanda real observada (MW)
- `forecast` — pronóstico de carga publicado (MW)

---

## Integración continua

`.github/workflows/entrega.yml` corre `pytest -m semana2` sobre Python 3.13 en
cada push a `main` y en cada pull request. La suite incluye un test que abre una
sesión MCP real y verifica el handshake, así que el protocolo se valida en cada
corrida.
