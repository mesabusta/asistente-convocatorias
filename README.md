# Asistente de Evaluación de Convocatorias y Conformación de Equipos

Centro de Proyectos y Consultoría — Universidad de los Alpes

Agente conversacional que evalúa si el Centro puede presentarse a una
convocatoria de financiación. Lee las bases desde una base de conocimiento
pública, autentica a los miembros del Centro y registra sus postulaciones
validando las políticas de la universidad.

**Integrantes:** [mesabusta](https://github.com/mesabusta) · [ysusecheo93](https://github.com/ysusecheo93)

**Principio de diseño:** entre más simple, mejor. La rúbrica de la semana 2 pide
al menos tres herramientas; el proyecto implementa exactamente tres, con el
patrón de los tutoriales del curso.

---

## El problema

El cuello de botella no es encontrar convocatorias: es decidir rápido a cuáles
vale la pena presentarse. Ese juicio cruza fuentes que viven separadas — las
bases de la convocatoria, el perfil real de cada miembro y las políticas de la
universidad — y el orden en que hay que consultarlas depende de lo que se va
encontrando. Si la convocatoria fija un overhead por debajo del mínimo
institucional, no vale la pena mirar el resto.

## Qué hace el agente

1. **Evalúa la intención antes de actuar.** Si la pregunta se resuelve con
   información pública, responde sin pedir identidad. Si la gestión es una
   postulación, autentica primero.
2. **Lee, no supone.** Toda cifra, requisito o política sale de una herramienta.
3. **Reporta brechas específicas.** No dice "no se puede": dice qué requisito
   falla y contra qué política (overhead, riesgo reputacional, duplicado).
4. **Confirma solo con evidencia.** Nunca afirma que una solicitud quedó creada
   sin el `ok=true` de la herramienta que la registró.

---

## Las tres herramientas

| Herramienta | Tipo | Requiere |
|---|---|---|
| `consultar_convocatoria` | Pública: encuentra y lee las bases | — |
| `autenticar` | Frontera: abre sesión con rol y devuelve el perfil propio | cédula + clave |
| `crear_solicitud` | Acción: registra la postulación tras validar brechas | sesión de **personal** |

**La autorización se verifica dentro de la herramienta, no en el prompt.** Un
modelo puede ser persuadido de ignorar una instrucción del system prompt; una
función que devuelve `{"ok": false}` no. Si el agente intentara crear una
solicitud con un token inválido o una sesión de directivo, la operación falla
del lado del servidor. Hay tests que ejercitan exactamente esos intentos.

---

## Arquitectura

```
Usuario
  │
  ▼
┌──────────────────────────────────────────────┐
│  Cliente LangGraph  (centro/graph.py)        │
│                                              │
│   agent_node ──► should_continue             │
│       ▲               │                      │
│       │               ▼                      │
│       └────────── tools_node                 │
└───────────────────────┬──────────────────────┘
                        │  JSON-RPC sobre stdio (MCP)
                        ▼
┌──────────────────────────────────────────────┐
│  Servidor FastMCP (centro/mcp_server.py)     │
│  3 herramientas · control de rol             │
└───────┬───────────────────────┬──────────────┘
        ▼                       ▼
  base_conocimiento/      datos_internos/
  (público, markdown)     (privado, autenticado)
```

El agente es *stateful*: el historial de mensajes viaja en el estado del grafo,
lo que permite encadenar varias herramientas antes de responder (el token de
`autenticar` llega a `crear_solicitud` por el historial). El cliente no declara
ninguna herramienta: las descubre en tiempo de ejecución con `load_mcp_tools()`.

---

## Estructura

```
base_conocimiento/       Información PÚBLICA, en markdown
  convocatorias/         6 convocatorias abiertas con sus bases completas
  politicas/             4 políticas de participación de la universidad
datos_internos/          Información PRIVADA, requiere autenticación
  personal.json          10 personas con experticia, nivel, dedicación, historial
  solicitudes.json       Solicitudes de postulación sembradas
centro/
  tools.py               Las tres herramientas (KB, sesiones y validaciones)
  mcp_server.py          Servidor FastMCP sobre stdio
  graph.py               Cliente LangGraph, ciclo ReAct, descubrimiento dinámico
  scripted_llm.py        LLM guionizado para tests y evidencia sin Ollama
  evidencia_flujo.py     Traza de los flujos de evidencia
tests/test_semana2.py    17 tests
wiki_semana2.md          Documento de reflexión de la entrega
```

---

## Instalación

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

En Linux o macOS: `python3 -m venv .venv && source .venv/bin/activate`.

## Uso

**Los flujos de evidencia**, con traza completa (entrada, decisión, resultado,
respuesta):

```powershell
python -m centro.evidencia_flujo         # los tres
python -m centro.evidencia_flujo 3       # solo el de manejo de error
```

| Flujo | Qué demuestra |
|---|---|
| 1 | Consulta pública: se responde sin pedir identidad |
| 2 | Postulación completa: autenticar → leer bases → crear solicitud |
| 3 | Manejo de error: `ok=false` con brecha de overhead, no se crea nada |

**Tests:**

```powershell
pytest -m semana2 -q
```

---

## Credenciales de prueba

Datos sintéticos de un caso de estudio; no corresponden a personas reales.

| Persona | Rol | Cédula | Clave |
|---|---|---|---|
| Luisa Ruiz | directivo | 1010234567 | 4821 |
| Carolina Pérez | personal | 1030456789 | 2964 |
| Ricardo Tovar | personal | 1080901234 | 3846 |

El resto está en `datos_internos/personal.json`.

---

## Integración continua

`.github/workflows/entrega.yml` ejecuta `pytest -m semana2` sobre Python 3.13 en
cada push a `main` y en cada pull request. La suite incluye un test que abre una
sesión MCP real y verifica que el servidor expone las tres herramientas, así que
el protocolo se valida en cada corrida.
