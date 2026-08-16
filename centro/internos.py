"""Datos **internos** del Centro: personal, sesiones y solicitudes.

Todo lo que hay aquí exige autenticación. Este módulo es el que sabe quién es
quién y qué puede hacer cada rol; `centro.kb` (lo público) no lo sabe y no debe
importarlo.

**Dónde vive la autorización.** La verificación de rol ocurre en este módulo y
en `centro.tools`, nunca en el prompt del agente. Un modelo puede ser
persuadido de ignorar una instrucción del system prompt; una función que
devuelve un error no. Si el agente intentara asignar una convocatoria con un
token de personal, la operación falla del lado del servidor.

El estado (sesiones, solicitudes, asignaciones) es en memoria, sembrado desde
`datos_internos/`. No se persiste a disco: el alcance del taller no lo requiere
y así el pipeline no depende del sistema de archivos ni del orden de los tests.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

ROOT = Path(__file__).resolve().parents[1]
DIR_INTERNOS = ROOT / "datos_internos"
ARCHIVO_PERSONAL = DIR_INTERNOS / "personal.json"
ARCHIVO_SOLICITUDES = DIR_INTERNOS / "solicitudes.json"

Rol = Literal["personal", "directivo"]

#: Campos del perfil que nunca salen de este módulo hacia una herramienta.
CAMPOS_SENSIBLES = {"clave"}


@dataclass
class Sesion:
    token: str
    cedula: str
    nombre: str
    rol: Rol


@dataclass
class _Estado:
    """Estado mutable del proceso: sesiones abiertas, solicitudes y asignaciones."""

    sesiones: dict[str, Sesion] = field(default_factory=dict)
    solicitudes: list[dict] = field(default_factory=list)
    asignaciones: dict[str, dict] = field(default_factory=dict)
    contador_solicitudes: int = 0


_estado = _Estado()


def _cargar_json(ruta: Path) -> list[dict]:
    return json.loads(ruta.read_text(encoding="utf-8"))


def personal() -> list[dict]:
    """Registro completo del personal, tal como está en disco."""
    return _cargar_json(ARCHIVO_PERSONAL)


def reiniciar_estado() -> None:
    """Devuelve el proceso al estado inicial: sin sesiones, solicitudes sembradas.

    Lo usan los tests y las demos para partir siempre del mismo punto.
    """
    global _estado
    semilla = _cargar_json(ARCHIVO_SOLICITUDES)
    _estado = _Estado(
        sesiones={},
        solicitudes=[dict(s) for s in semilla],
        asignaciones={},
        contador_solicitudes=len(semilla),
    )


def _asegurar_estado() -> None:
    if not _estado.solicitudes and _estado.contador_solicitudes == 0:
        reiniciar_estado()


def _buscar_persona(cedula: str) -> Optional[dict]:
    for persona in personal():
        if persona["cedula"] == cedula.strip():
            return persona
    return None


def perfil_publico(persona: dict) -> dict:
    """Copia del perfil sin los campos sensibles (la clave nunca se expone)."""
    return {k: v for k, v in persona.items() if k not in CAMPOS_SENSIBLES}


def _generar_token(cedula: str) -> str:
    """Token opaco derivado de la cédula y del número de sesiones abiertas.

    No se usa `secrets` a propósito: el token debe ser reproducible para que la
    evidencia y los tests sean deterministas. En un sistema real sería
    aleatorio y con expiración.
    """
    semilla = f"{cedula}:{len(_estado.sesiones)}"
    return "ses_" + hashlib.sha256(semilla.encode()).hexdigest()[:16]


def autenticar(cedula: str, clave: str) -> tuple[Optional[Sesion], Optional[str]]:
    """Valida credenciales y abre una sesión.

    Devuelve `(sesion, None)` si las credenciales son válidas, o
    `(None, mensaje_de_error)` si no. El mensaje de error es deliberadamente
    genérico: no revela si falló la cédula o la clave.
    """
    _asegurar_estado()
    persona = _buscar_persona(cedula)
    if persona is None or persona["clave"] != str(clave).strip():
        return None, "Credenciales inválidas. Verifique la cédula y la clave de 4 dígitos."
    sesion = Sesion(
        token=_generar_token(persona["cedula"]),
        cedula=persona["cedula"],
        nombre=persona["nombre"],
        rol=persona["rol"],
    )
    _estado.sesiones[sesion.token] = sesion
    return sesion, None


def resolver_sesion(token: str) -> tuple[Optional[Sesion], Optional[str]]:
    """Traduce un token a una sesión abierta."""
    _asegurar_estado()
    sesion = _estado.sesiones.get(str(token).strip())
    if sesion is None:
        return None, "Sesión no válida o expirada. Debe autenticarse de nuevo."
    return sesion, None


def exigir_rol(token: str, rol_requerido: Rol) -> tuple[Optional[Sesion], Optional[str]]:
    """Resuelve la sesión y verifica que tenga el rol exigido.

    Este es el punto único donde se decide si una operación interna procede.
    """
    sesion, error = resolver_sesion(token)
    if error:
        return None, error
    assert sesion is not None
    if sesion.rol != rol_requerido:
        return None, (
            f"La operación requiere rol '{rol_requerido}' y la sesión tiene rol "
            f"'{sesion.rol}'. {_explicacion_rol(rol_requerido)}"
        )
    return sesion, None


def _explicacion_rol(rol_requerido: Rol) -> str:
    if rol_requerido == "directivo":
        return (
            "Ver a todo el personal, revisar las solicitudes y asignar una "
            "convocatoria son decisiones exclusivas de la Dirección del Centro."
        )
    return "Solo el personal del Centro crea solicitudes de postulación."


# --------------------------------------------------------------------------
# Solicitudes y asignaciones
# --------------------------------------------------------------------------


def solicitudes_de(convocatoria_id: Optional[str] = None) -> list[dict]:
    _asegurar_estado()
    if convocatoria_id is None:
        return list(_estado.solicitudes)
    objetivo = convocatoria_id.strip().upper()
    return [s for s in _estado.solicitudes if s["convocatoria_id"].upper() == objetivo]


def existe_solicitud(convocatoria_id: str, cedula: str) -> bool:
    return any(
        s["convocatoria_id"].upper() == convocatoria_id.strip().upper()
        and s["cedula"] == cedula
        for s in solicitudes_de()
    )


def registrar_solicitud(
    convocatoria_id: str,
    cedula: str,
    nombre: str,
    rol_propuesto: str,
    justificacion: str,
) -> dict:
    _asegurar_estado()
    _estado.contador_solicitudes += 1
    solicitud = {
        "id": f"SOL-{_estado.contador_solicitudes:04d}",
        "convocatoria_id": convocatoria_id.strip().upper(),
        "cedula": cedula,
        "nombre": nombre,
        "rol_propuesto": rol_propuesto,
        "justificacion": justificacion,
        "estado": "pendiente",
    }
    _estado.solicitudes.append(solicitud)
    return solicitud


def registrar_asignacion(
    convocatoria_id: str,
    integrantes: list[dict],
    justificacion: str,
    decidida_por: str,
) -> dict:
    _asegurar_estado()
    clave = convocatoria_id.strip().upper()
    asignacion = {
        "convocatoria_id": clave,
        "integrantes": integrantes,
        "justificacion": justificacion,
        "decidida_por": decidida_por,
    }
    _estado.asignaciones[clave] = asignacion
    for solicitud in _estado.solicitudes:
        if solicitud["convocatoria_id"].upper() != clave:
            continue
        cedulas = {i["cedula"] for i in integrantes}
        solicitud["estado"] = "asignada" if solicitud["cedula"] in cedulas else "no_seleccionada"
    return asignacion


def asignacion_de(convocatoria_id: str) -> Optional[dict]:
    _asegurar_estado()
    return _estado.asignaciones.get(convocatoria_id.strip().upper())
