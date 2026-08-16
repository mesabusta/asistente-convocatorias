"""Las tres herramientas del asistente de convocatorias.

La rúbrica de la semana 2 pide al menos tres tools; el caso necesita tres
capacidades esenciales. Una tool por capacidad — el mismo principio de
granularidad fina del tutorial del curso (convert_units / calculate /
get_weather): cada herramienta hace exactamente una cosa y todos sus
parámetros son siempre relevantes.

1. ``consultar_convocatoria`` — **pública**. Encuentra y lee las bases de una
   convocatoria. No pide identidad.
2. ``autenticar`` — **frontera**. Convierte cédula y clave en un token de
   sesión con rol, y devuelve el perfil propio.
3. ``crear_solicitud`` — **acción**. Registra la postulación del usuario
   autenticado, después de validar las brechas de política.

Contrato de retorno: todas devuelven un string JSON. Éxito: ``{"ok": true}``.
Error o resultado inesperado: ``{"ok": false, "error": "..."}``. Un
``ok=false`` no es una excepción: es información que el agente debe leer y
comunicar (la brecha concreta, no un rechazo genérico).

**La autorización se verifica aquí, no en el prompt.** ``crear_solicitud``
valida el token y el rol antes de tocar un dato: si el modelo alucinara la
llamada con un token inválido o un rol equivocado, la herramienta la rechaza
igual.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import Field

ROOT = Path(__file__).resolve().parents[1]
DIR_CONVOCATORIAS = ROOT / "base_conocimiento" / "convocatorias"
ARCHIVO_PERSONAL = ROOT / "datos_internos" / "personal.json"
ARCHIVO_SOLICITUDES = ROOT / "datos_internos" / "solicitudes.json"

#: Overhead mínimo institucional según el tipo de entidad convocante
#: (política POL-FIN-001, `base_conocimiento/politicas/overhead-y-contrapartida.md`).
OVERHEAD_MINIMO = {
    "organismo_internacional": 15,
    "publica_nacional": 12,
    "privada": 20,
    "fundacion": 10,
}

#: Sectores con restricción reputacional (política POL-RIE-002).
SECTORES_RESTRINGIDOS = {"extractivo", "armas", "tabaco", "juegos_de_azar"}


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _error(mensaje: str, **extra) -> str:
    return _json({"ok": False, "error": mensaje, **extra})


# ==========================================================================
# Base de conocimiento pública (markdown con frontmatter YAML)
# ==========================================================================


def _partir_frontmatter(texto: str) -> tuple[dict, str]:
    """Separa el frontmatter YAML del cuerpo markdown."""
    if not texto.startswith("---"):
        return {}, texto
    partes = texto.split("---", 2)
    if len(partes) < 3:
        return {}, texto
    meta = yaml.safe_load(partes[1]) or {}
    return (meta if isinstance(meta, dict) else {}), partes[2].strip()


@lru_cache(maxsize=1)
def _convocatorias() -> tuple[dict, ...]:
    """Carga las convocatorias abiertas: metadatos + texto completo."""
    documentos = []
    for ruta in sorted(DIR_CONVOCATORIAS.glob("*.md")):
        meta, cuerpo = _partir_frontmatter(ruta.read_text(encoding="utf-8"))
        if str(meta.get("estado", "abierta")) == "abierta":
            documentos.append({**meta, "id": str(meta.get("id", ruta.stem)), "texto": cuerpo})
    return tuple(documentos)


def _resumen(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "titulo": doc.get("titulo"),
        "entidad": doc.get("entidad"),
        "tipo": doc.get("tipo"),
        "area": doc.get("area"),
        "cierre": str(doc.get("cierre")),
    }


# ==========================================================================
# Estado interno: personal, sesiones y solicitudes
# ==========================================================================

_sesiones: dict[str, dict] = {}
_solicitudes: list[dict] = []
_contador: list[int] = [0]  # lista para poder mutarlo sin `global`


def reiniciar_estado() -> None:
    """Estado inicial: sin sesiones, solicitudes sembradas desde disco."""
    semilla = json.loads(ARCHIVO_SOLICITUDES.read_text(encoding="utf-8"))
    _sesiones.clear()
    _solicitudes.clear()
    _solicitudes.extend(dict(s) for s in semilla)
    _contador[0] = len(semilla)


def _asegurar_estado() -> None:
    if not _solicitudes and _contador[0] == 0:
        reiniciar_estado()


def _personal() -> list[dict]:
    return json.loads(ARCHIVO_PERSONAL.read_text(encoding="utf-8"))


# ==========================================================================
# Tool 1 — consultar_convocatoria (pública, sin autenticación)
# ==========================================================================


def consultar_convocatoria(
    consulta: Annotated[
        str,
        Field(
            description=(
                "Identificador (p.ej. BID-2026-EDU-014) o texto libre para buscar "
                "(p.ej. 'educación superior', 'Minciencias')"
            )
        ),
    ],
) -> str:
    """Encuentra una convocatoria abierta y devuelve sus bases completas.

    Información pública: no requiere autenticación. Si la consulta coincide con
    varias convocatorias devuelve la lista de resúmenes para precisar; si no
    coincide con ninguna, el error incluye los identificadores disponibles.

    El detalle incluye las condiciones (monto, overhead, cierre), el overhead
    mínimo institucional aplicable (POL-FIN-001) y las señales de riesgo
    reputacional detectables (POL-RIE-002), para que el agente pueda reportar
    brechas leyendo solo fuentes públicas.
    """
    objetivo = consulta.strip().lower()
    docs = _convocatorias()

    encontradas = [d for d in docs if objetivo == d["id"].lower()]
    if not encontradas:
        encontradas = [d for d in docs if objetivo in d["id"].lower()]
    if not encontradas:
        encontradas = [
            d
            for d in docs
            if objetivo in " ".join(str(v) for v in d.values()).lower()
        ]

    if not encontradas:
        return _error(
            f"Ninguna convocatoria abierta coincide con '{consulta}'.",
            ids_disponibles=[d["id"] for d in docs],
        )
    if len(encontradas) > 1:
        return _json(
            {
                "ok": True,
                "fuente": "publica",
                "nota": "Varias convocatorias coinciden; consulte una por su id.",
                "convocatorias": [_resumen(d) for d in encontradas],
            }
        )

    doc = encontradas[0]
    tipo_entidad = str(doc.get("tipo_entidad", ""))
    sector = str(doc.get("sector_entidad", ""))
    señales = []
    if sector in SECTORES_RESTRINGIDOS:
        señales.append(
            f"La entidad pertenece a un sector con restricción reputacional: {sector} (POL-RIE-002)."
        )
    if doc.get("monto_cop") is None:
        señales.append("El presupuesto se declara 'a convenir': no hay valor de referencia público.")

    return _json(
        {
            "ok": True,
            "fuente": "publica",
            **_resumen(doc),
            "monto_cop": doc.get("monto_cop"),
            "overhead_maximo_pct": doc.get("overhead_maximo_pct"),
            "overhead_minimo_institucional_pct": OVERHEAD_MINIMO.get(tipo_entidad),
            "señales_de_riesgo": señales,
            "texto": doc["texto"],
        }
    )


# ==========================================================================
# Tool 2 — autenticar (frontera entre lo público y lo interno)
# ==========================================================================


def autenticar(
    cedula: Annotated[str, Field(description="Número de cédula del miembro del Centro")],
    clave: Annotated[str, Field(description="Clave numérica de 4 dígitos")],
) -> str:
    """Valida credenciales y abre una sesión con un rol asociado.

    Devuelve el token que exige ``crear_solicitud`` y el perfil propio
    (experticia, nivel, dedicación, historial) — nunca el de otra persona y
    nunca la clave. El mensaje de error es deliberadamente genérico: no revela
    si falló la cédula o la clave.
    """
    _asegurar_estado()
    persona = next((p for p in _personal() if p["cedula"] == cedula.strip()), None)
    if persona is None or persona["clave"] != str(clave).strip():
        return _error("Credenciales inválidas. Verifique la cédula y la clave de 4 dígitos.")

    token = "ses_" + hashlib.sha256(f"{persona['cedula']}:{len(_sesiones)}".encode()).hexdigest()[:16]
    _sesiones[token] = {"cedula": persona["cedula"], "nombre": persona["nombre"], "rol": persona["rol"]}
    return _json(
        {
            "ok": True,
            "fuente": "interna",
            "token": token,
            "rol": persona["rol"],
            "perfil": {k: v for k, v in persona.items() if k != "clave"},
        }
    )


# ==========================================================================
# Tool 3 — crear_solicitud (acción; exclusiva del rol personal)
# ==========================================================================


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
    """Crea una solicitud de postulación a nombre del usuario autenticado.

    **Exclusiva del rol personal** (el personal se postula; la asignación final
    es de la Dirección). Antes de registrar valida, en orden: sesión y rol,
    que la convocatoria exista, que no tenga restricción reputacional, que su
    overhead no esté bajo el mínimo institucional y que no sea un duplicado.
    Si algo falla no crea nada y devuelve la brecha concreta.
    """
    _asegurar_estado()
    sesion = _sesiones.get(str(token).strip())
    if sesion is None:
        return _error("Sesión no válida o expirada. Debe autenticarse de nuevo.")
    if sesion["rol"] != "personal":
        return _error(
            f"La operación requiere rol 'personal' y la sesión tiene rol '{sesion['rol']}'. "
            "Solo el personal del Centro crea solicitudes de postulación; la asignación "
            "de equipos es una decisión exclusiva de la Dirección."
        )

    objetivo = convocatoria_id.strip().upper()
    doc = next((d for d in _convocatorias() if d["id"].upper() == objetivo), None)
    if doc is None:
        return _error(
            f"No existe una convocatoria con identificador '{convocatoria_id}'.",
            ids_disponibles=[d["id"] for d in _convocatorias()],
        )

    sector = str(doc.get("sector_entidad", ""))
    if sector in SECTORES_RESTRINGIDOS:
        return _error(
            f"No puede crearse una solicitud: la entidad pertenece al sector '{sector}', con "
            "restricción reputacional (POL-RIE-002). El caso requiere concepto del Comité de "
            "Ética y Reputación: debe escalarse, no resolverse aquí.",
            brecha="riesgo_reputacional",
        )

    minimo = OVERHEAD_MINIMO.get(str(doc.get("tipo_entidad", "")))
    tope = doc.get("overhead_maximo_pct")
    if minimo is not None and tope is not None and tope < minimo:
        return _error(
            f"No puede crearse una solicitud: la convocatoria reconoce un overhead máximo del "
            f"{tope}% y el mínimo institucional para ese tipo de entidad es {minimo}% "
            "(POL-FIN-001). Requiere exención de la Vicerrectoría, que tramita la Dirección.",
            brecha="overhead",
            overhead_convocatoria_pct=tope,
            overhead_minimo_institucional_pct=minimo,
        )

    if any(s["convocatoria_id"].upper() == objetivo and s["cedula"] == sesion["cedula"] for s in _solicitudes):
        return _error(
            f"{sesion['nombre']} ya tiene una solicitud registrada para '{objetivo}'.",
            brecha="duplicada",
        )

    _contador[0] += 1
    solicitud = {
        "id": f"SOL-{_contador[0]:04d}",
        "convocatoria_id": objetivo,
        "cedula": sesion["cedula"],
        "nombre": sesion["nombre"],
        "rol_propuesto": rol_propuesto,
        "justificacion": justificacion,
        "estado": "pendiente",
    }
    _solicitudes.append(solicitud)
    return _json(
        {
            "ok": True,
            "fuente": "interna",
            "accion": "solicitud_creada",
            "solicitud": solicitud,
            "nota": (
                "La solicitud queda en estado pendiente. La asignación final del equipo "
                "es una decisión de la Dirección del Centro."
            ),
        }
    )


def solicitudes_de(convocatoria_id: str | None = None) -> list[dict]:
    """Solicitudes registradas (para tests y evidencia)."""
    _asegurar_estado()
    if convocatoria_id is None:
        return list(_solicitudes)
    objetivo = convocatoria_id.strip().upper()
    return [s for s in _solicitudes if s["convocatoria_id"].upper() == objetivo]
