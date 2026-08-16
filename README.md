# Asistente de Evaluación de Convocatorias y Conformación de Equipos

Centro de Proyectos y Consultoría — Universidad de los Alpes

Agente conversacional que evalúa si el Centro puede presentarse a una
convocatoria de financiación y, cuando puede, ayuda a conformar el equipo.
Lee las bases y las políticas desde una base de conocimiento pública, contrasta
contra los datos internos del Centro, y respeta dos roles con capacidades
distintas.

**Integrantes:** [mesabusta](https://github.com/mesabusta) · [ysusecheo93](https://github.com/ysusecheo93)

---

## El problema

El cuello de botella no es encontrar convocatorias: es decidir rápido a cuáles
vale la pena presentarse y con qué equipo. Ese juicio cruza tres fuentes que
viven separadas — las bases de la convocatoria, el personal real del Centro y
las políticas de la universidad — y el orden en que hay que consultarlas depende
de lo que se va encontrando. Si la entidad exige un consorcio internacional que
no existe, no vale la pena mirar el resto.

## Qué hace el agente

1. **Evalúa la intención antes de actuar.** Si la pregunta se resuelve con
   información pública, responde sin pedir identidad. Si toca datos internos o
   ejecuta una acción, autentica primero.
2. **Lee, no supone.** Toda cifra, requisito o política sale de una herramienta.
3. **Respeta el rol.** El personal consulta su propio perfil y crea solicitudes.
   Solo un directivo ve a todo el personal, revisa solicitudes y asigna.
4. **Reporta brechas específicas.** No dice "no se puede": dice qué requisito
   falta y contra qué política.
5. **Escala cuando debe.** Ante riesgo reputacional o un caso ambiguo, entrega
   un resumen estructurado al equipo humano en vez de decidir.

---

## Las diez herramientas

| Grupo | Herramienta | Requiere |
|---|---|---|
| Pública | `buscar_convocatorias` | — |
| Pública | `leer_convocatoria` | — |
| Pública | `consultar_politica` | — |
| Frontera | `autenticar` | cédula + clave |
| Interna | `consultar_perfil` | sesión (cualquier rol, solo el propio) |
| Interna | `listar_personal` | sesión de **directivo** |
| Interna | `listar_solicitudes` | sesión de **directivo** |
| Acción | `crear_solicitud` | sesión de **personal** |
| Acción | `asignar_convocatoria` | sesión de **directivo** |
| Acción | `escalar_a_humanos` | — |

**La autorización se verifica dentro de la herramienta, no en el prompt.** Un
modelo puede ser persuadido de ignorar una instrucción del system prompt; una
función que devuelve `{"ok": false}` no. Si el agente intentara asignar una
convocatoria con un token de personal, la operación falla del lado del servidor.
Hay un test que ejercita exactamente ese intento.

---

## Arquitectura

```
Usuario
  │
  ▼
┌──────────────────────────────────────────────┐
│  Cliente LangGraph  (centro/graph.py)        │
│                                              │
│   agent_node ──► should_continue              │
│       ▲               │                       │
│       │               ▼                       │
│       └────────── tools_node                  │
└───────────────────────┬──────────────────────┘
                        │  JSON-RPC sobre stdio (MCP)
                        ▼
┌──────────────────────────────────────────────┐
│  Servidor FastMCP (centro/mcp_server.py)     │
│  10 herramientas · control de rol            │
└───────┬───────────────────────┬──────────────┘
        ▼                       ▼
  base_conocimiento/      datos_internos/
  (público, markdown)     (privado, autenticado)
```

El agente es *stateful*: el historial de mensajes viaja en el estado del grafo,
lo que permite encadenar varias herramientas antes de responder. El número de
iteraciones no lo fija el diseño — lo fija lo que devuelven las herramientas.

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
  kb.py                  Carga y búsqueda en la base de conocimiento pública
  internos.py            Personal, sesiones, roles y solicitudes
  tools.py               Las diez herramientas
  mcp_server.py          Servidor FastMCP sobre stdio
  graph.py               Cliente LangGraph, ciclo ReAct, descubrimiento dinámico
  scripted_llm.py        LLM guionizado para tests y evidencia sin Ollama
  evidencia_flujo.py     Traza completa de las cuatro situaciones
tests/test_semana2.py    35 tests
wiki_semana2.md          Documento de reflexión
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

**Las cuatro situaciones del caso**, con traza completa:

```powershell
python -m centro.evidencia_flujo         # las cuatro
python -m centro.evidencia_flujo C       # solo la de riesgo reputacional
```

| Situación | Qué demuestra |
|---|---|
| A | Brecha de política: dos requisitos incumplidos, no se crea solicitud |
| B | Personal autenticado que sí encaja: se crea la solicitud |
| C | Riesgo reputacional: el agente escala en vez de decidir |
| D | Directiva que revisa solicitudes y asigna el equipo con justificación |

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
sesión MCP real y verifica que el servidor expone las diez herramientas, así que
el protocolo se valida en cada corrida.
