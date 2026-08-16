"""Las diez herramientas del asistente de convocatorias.

Están organizadas en cuatro grupos según lo que exigen del usuario:

1. **Públicas** — `buscar_convocatorias`, `leer_convocatoria`, `consultar_politica`.
   No piden identidad. Responden desde la base de conocimiento pública.
2. **Frontera** — `autenticar`. Convierte cédula y clave en un token con rol.
3. **Lectura interna** — `consultar_perfil` (cualquier rol, solo lo propio) y
   `listar_personal` (solo directivo).
4. **Acciones** — `crear_solicitud` (solo personal), `listar_solicitudes` y
   `asignar_convocatoria` (solo directivo), y `escalar_a_humanos` (cualquiera).

Todas devuelven un string con JSON y el mismo contrato de error:
`{"ok": false, "error": "..."}`. Un `ok=false` no es una excepción: es
información que el agente debe leer y comunicar, y con la que puede decidir
reintentar por otro camino.

**La autorización se verifica aquí, no en el prompt.** Cada herramienta interna
llama a `internos.exigir_rol` antes de tocar un dato. Si el modelo alucinara una
llamada a `asignar_convocatoria` con un token de personal, la herramienta la
rechaza igual.
"""

from __future__ import annotations

import json
from typing import Annotated, Optional

from pydantic import Field

from centro import internos, kb

#: Overhead mínimo institucional según el tipo de entidad convocante.
#: Refleja la tabla de `base_conocimiento/politicas/overhead-y-contrapartida.md`.
OVERHEAD_MINIMO = {
    "organismo_internacional": 15,
    "publica_nacional": 12,
    "privada": 20,
    "fundacion": 10,
}

#: Sectores con restricción reputacional (POL-RIE-002).
SECTORES_RESTRINGIDOS = {"extractivo", "armas", "tabaco", "juegos_de_azar"}


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _error(mensaje: str, **extra) -> str:
    return _json({"ok": False, "error": mensaje, **extra})


# ==========================================================================
# 1. Herramientas públicas — no requieren autenticación
# ==========================================================================


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
        Optional[str],
        Field(description="Texto libre a buscar en el contenido de la convocatoria, p.ej. 'permanencia' o 'BID'"),
    ] = None,
) -> str:
    """Lista las convocatorias abiertas, filtrando por área, tipo o texto libre.

    Información pública: no requiere autenticación. Devuelve un resumen de cada
    convocatoria; para las condiciones completas hay que leerla.
    """
    encontradas = kb.buscar_convocatorias(area=area, tipo=tipo, texto=texto)
    if not encontradas:
        disponibles = sorted({str(d.meta.get("area", "")) for d in kb.convocatorias()})
        return _error(
            "No hay convocatorias abiertas que coincidan con esos filtros.",
            areas_disponibles=disponibles,
        )
    return _json(
        {
            "ok": True,
            "fuente": "publica",
            "n_resultados": len(encontradas),
            "convocatorias": [
                {
                    "id": d.id,
                    "titulo": d.titulo,
                    "entidad": d.meta.get("entidad"),
                    "tipo": d.meta.get("tipo"),
                    "area": d.meta.get("area"),
                    "monto_cop": d.meta.get("monto_cop") or d.meta.get("monto_declarado"),
                    "cierre": str(d.meta.get("cierre")),
                }
                for d in encontradas
            ],
        }
    )


def leer_convocatoria(
    convocatoria_id: Annotated[
        str, Field(description="Identificador de la convocatoria, p.ej. BID-2026-EDU-014")
    ],
) -> str:
    """Lee las bases completas de una convocatoria desde la base de conocimiento.

    Devuelve el texto del documento junto con las condiciones extraídas del
    frontmatter (montos, topes, plazos) y las señales de riesgo detectables por
    la política de sectores restringidos. Información pública.
    """
    doc = kb.obtener_convocatoria(convocatoria_id)
    if doc is None:
        return _error(
            f"No existe una convocatoria con identificador '{convocatoria_id}'.",
            ids_disponibles=[d.id for d in kb.convocatorias()],
        )

    tipo_entidad = str(doc.meta.get("tipo_entidad", ""))
    sector = str(doc.meta.get("sector_entidad", ""))
    señales = []
    if sector in SECTORES_RESTRINGIDOS:
        señales.append(f"La entidad pertenece a un sector con restricción reputacional: {sector}.")
    if doc.meta.get("monto_cop") is None:
        señales.append("El presupuesto se declara 'a convenir': no hay valor de referencia público.")

    return _json(
        {
            "ok": True,
            "fuente": "publica",
            "id": doc.id,
            "titulo": doc.titulo,
            "entidad": doc.meta.get("entidad"),
            "tipo_entidad": tipo_entidad,
            "sector_entidad": sector or None,
            "tipo": doc.meta.get("tipo"),
            "area": doc.meta.get("area"),
            "monto_cop": doc.meta.get("monto_cop"),
            "monto_declarado": doc.meta.get("monto_declarado"),
            "overhead_maximo_pct": doc.meta.get("overhead_maximo_pct"),
            "contrapartida_minima_pct": doc.meta.get("contrapartida_minima_pct"),
            "cierre": str(doc.meta.get("cierre")),
            "overhead_minimo_institucional_pct": OVERHEAD_MINIMO.get(tipo_entidad),
            "señales_de_riesgo": señales,
            "texto": doc.cuerpo,
        }
    )


def consultar_politica(
    tema: Annotated[
        str,
        Field(description="Tema de la política: overhead, contrapartida, riesgo reputacional, autorización, conflicto de interés"),
    ],
) -> str:
    """Lee la política de participación de la universidad relevante para un tema.

    Las políticas son información pública y viven en la misma base de
    conocimiento que las convocatorias. No requiere autenticación.
    """
    doc = kb.buscar_politica(tema)
    if doc is None:
        return _error(
            f"No se encontró una política asociada al tema '{tema}'.",
            politicas_disponibles=[{"id": d.id, "titulo": d.titulo} for d in kb.politicas()],
        )
    return _json(
        {
            "ok": True,
            "fuente": "publica",
            "id": doc.id,
            "titulo": doc.titulo,
            "texto": doc.cuerpo,
        }
    )


# ==========================================================================
# 2. Frontera — autenticación
# ==========================================================================


def autenticar(
    cedula: Annotated[str, Field(description="Número de cédula del miembro del Centro")],
    clave: Annotated[str, Field(description="Clave numérica de 4 dígitos")],
) -> str:
    """Valida credenciales y abre una sesión con un rol asociado.

    Devuelve un token que las herramientas internas exigen. El token lleva el
    rol: quien se autentica como personal no puede ejecutar acciones de
    directivo aunque lo pida explícitamente.
    """
    sesion, error = internos.autenticar(cedula, clave)
    if error:
        return _error(error)
    assert sesion is not None
    capacidades = (
        ["consultar_perfil", "crear_solicitud", "escalar_a_humanos"]
        if sesion.rol == "personal"
        else [
            "consultar_perfil",
            "listar_personal",
            "listar_solicitudes",
            "asignar_convocatoria",
            "escalar_a_humanos",
        ]
    )
    return _json(
        {
            "ok": True,
            "token": sesion.token,
            "nombre": sesion.nombre,
            "rol": sesion.rol,
            "capacidades": capacidades,
        }
    )


# ==========================================================================
# 3. Lectura interna — requiere sesión
# ==========================================================================


def consultar_perfil(
    token: Annotated[str, Field(description="Token de sesión devuelto por autenticar")],
) -> str:
    """Devuelve el perfil del usuario autenticado: experticia, nivel, historial.

    Cualquier rol puede consultar **su propio** perfil. No permite consultar el
    de otra persona: no recibe cédula como parámetro, justamente para que no
    exista esa posibilidad.
    """
    sesion, error = internos.resolver_sesion(token)
    if error:
        return _error(error)
    assert sesion is not None
    persona = next((p for p in internos.personal() if p["cedula"] == sesion.cedula), None)
    if persona is None:
        return _error("La sesión es válida pero el perfil no está en el registro del Centro.")
    return _json({"ok": True, "fuente": "interna", "perfil": internos.perfil_publico(persona)})


def listar_personal(
    token: Annotated[str, Field(description="Token de sesión de un directivo")],
    area: Annotated[
        Optional[str], Field(description="Filtra por área de experticia, p.ej. politica_publica")
    ] = None,
) -> str:
    """Lista a todo el personal del Centro con su experticia, nivel e historial.

    **Exclusiva de directivos.** Un token de personal recibe un error: el
    personal no puede ver los datos de otros.
    """
    sesion, error = internos.exigir_rol(token, "directivo")
    if error:
        return _error(error)
    assert sesion is not None
    equipo = [internos.perfil_publico(p) for p in internos.personal()]
    if area:
        equipo = [p for p in equipo if area.lower() in [e.lower() for e in p["experticia"]]]
    if not equipo:
        return _error(f"Ningún miembro del Centro tiene experticia en '{area}'.", brecha="experticia")
    return _json(
        {
            "ok": True,
            "fuente": "interna",
            "consultado_por": sesion.nombre,
            "n_personas": len(equipo),
            "personal": equipo,
        }
    )


def listar_solicitudes(
    token: Annotated[str, Field(description="Token de sesión de un directivo")],
    convocatoria_id: Annotated[
        Optional[str], Field(description="Filtra por convocatoria. Si se omite, devuelve todas")
    ] = None,
) -> str:
    """Lista las solicitudes de postulación creadas por el personal.

    **Exclusiva de directivos.** Es el insumo para decidir el equipo: muestra
    quién se postuló, en qué rol y con qué justificación.
    """
    sesion, error = internos.exigir_rol(token, "directivo")
    if error:
        return _error(error)
    assert sesion is not None
    solicitudes = internos.solicitudes_de(convocatoria_id)
    if not solicitudes:
        return _error(
            "No hay solicitudes registradas"
            + (f" para la convocatoria '{convocatoria_id}'." if convocatoria_id else "."),
            brecha="sin_solicitudes",
        )
    return _json(
        {
            "ok": True,
            "fuente": "interna",
            "n_solicitudes": len(solicitudes),
            "solicitudes": solicitudes,
        }
    )


# ==========================================================================
# 4. Acciones
# ==========================================================================


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
    """Crea una solicitud de postulación a nombre del usuario autenticado.

    **Exclusiva del personal.** Antes de registrar verifica tres cosas: que la
    convocatoria exista, que no tenga señales de riesgo reputacional activas y
    que el overhead que ofrece no esté por debajo del mínimo institucional. Si
    alguna falla, no crea nada y devuelve la brecha.

    El personal se postula; no se asigna. La asignación es de la Dirección.
    """
    sesion, error = internos.exigir_rol(token, "personal")
    if error:
        return _error(error)
    assert sesion is not None

    doc = kb.obtener_convocatoria(convocatoria_id)
    if doc is None:
        return _error(f"No existe una convocatoria con identificador '{convocatoria_id}'.")

    sector = str(doc.meta.get("sector_entidad", ""))
    if sector in SECTORES_RESTRINGIDOS:
        return _error(
            f"No puede crearse una solicitud: la entidad pertenece al sector '{sector}', "
            "con restricción reputacional. El caso requiere concepto del Comité de Ética "
            "y Reputación (POL-RIE-002).",
            brecha="riesgo_reputacional",
            requiere_escalamiento=True,
        )

    tipo_entidad = str(doc.meta.get("tipo_entidad", ""))
    minimo = OVERHEAD_MINIMO.get(tipo_entidad)
    tope = doc.meta.get("overhead_maximo_pct")
    if minimo is not None and tope is not None and tope < minimo:
        return _error(
            f"No puede crearse una solicitud: la convocatoria reconoce un overhead máximo "
            f"del {tope}% y el mínimo institucional para una entidad de tipo "
            f"'{tipo_entidad}' es {minimo}% (POL-FIN-001). Requiere exención de la "
            "Vicerrectoría de Investigación, que debe tramitar la Dirección del Centro.",
            brecha="overhead",
            overhead_convocatoria_pct=tope,
            overhead_minimo_institucional_pct=minimo,
        )

    if internos.existe_solicitud(convocatoria_id, sesion.cedula):
        return _error(
            f"{sesion.nombre} ya tiene una solicitud registrada para '{convocatoria_id}'.",
            brecha="duplicada",
        )

    solicitud = internos.registrar_solicitud(
        convocatoria_id=convocatoria_id,
        cedula=sesion.cedula,
        nombre=sesion.nombre,
        rol_propuesto=rol_propuesto,
        justificacion=justificacion,
    )
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


def asignar_convocatoria(
    token: Annotated[str, Field(description="Token de sesión de un directivo")],
    convocatoria_id: Annotated[str, Field(description="Identificador de la convocatoria")],
    cedulas: Annotated[
        list[str], Field(description="Cédulas del personal que conformará el equipo")
    ],
    justificacion: Annotated[
        str,
        Field(description="Por qué ese equipo, contrastado con los criterios de evaluación de la convocatoria"),
    ],
) -> str:
    """Asigna una convocatoria a un equipo concreto del Centro.

    **Exclusiva de directivos.** Exige justificación: una asignación sin razones
    contra los criterios de evaluación se rechaza. Verifica que cada cédula
    exista y que la convocatoria no tenga restricción reputacional activa.
    """
    sesion, error = internos.exigir_rol(token, "directivo")
    if error:
        return _error(error)
    assert sesion is not None

    doc = kb.obtener_convocatoria(convocatoria_id)
    if doc is None:
        return _error(f"No existe una convocatoria con identificador '{convocatoria_id}'.")

    sector = str(doc.meta.get("sector_entidad", ""))
    if sector in SECTORES_RESTRINGIDOS:
        return _error(
            f"No puede asignarse un equipo: la entidad pertenece al sector '{sector}', "
            "con restricción reputacional (POL-RIE-002). Requiere concepto previo del "
            "Comité de Ética y Reputación.",
            brecha="riesgo_reputacional",
            requiere_escalamiento=True,
        )

    if not cedulas:
        return _error("Debe indicarse al menos una persona para conformar el equipo.")

    if not justificacion or len(justificacion.strip()) < 20:
        return _error(
            "La asignación exige una justificación explícita contra los criterios de "
            "evaluación de la convocatoria."
        )

    registro = {p["cedula"]: p for p in internos.personal()}
    desconocidas = [c for c in cedulas if c not in registro]
    if desconocidas:
        return _error(
            f"Estas cédulas no corresponden a personal del Centro: {desconocidas}.",
            brecha="persona_inexistente",
        )

    integrantes = [
        {
            "cedula": c,
            "nombre": registro[c]["nombre"],
            "nivel": registro[c]["nivel"],
            "dedicacion": registro[c]["dedicacion"],
            "experticia": registro[c]["experticia"],
        }
        for c in cedulas
    ]
    asignacion = internos.registrar_asignacion(
        convocatoria_id=convocatoria_id,
        integrantes=integrantes,
        justificacion=justificacion,
        decidida_por=sesion.nombre,
    )
    return _json(
        {
            "ok": True,
            "fuente": "interna",
            "accion": "convocatoria_asignada",
            "asignacion": asignacion,
        }
    )


def escalar_a_humanos(
    motivo: Annotated[
        str, Field(description="Por qué el caso supera la capacidad del asistente")
    ],
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
    """Escala el caso al equipo humano con un resumen estructurado.

    No decide: documenta. Devuelve el paquete que recibe el Comité de Ética o la
    Dirección, para que no tengan que rehacer el análisis desde cero. Disponible
    para cualquier usuario, con o sin sesión.
    """
    if not motivo or not motivo.strip():
        return _error("El escalamiento exige un motivo explícito.")

    destinatario = "Comité de Ética y Reputación"
    texto = motivo.lower()
    if "autorizacion" in texto or "autorización" in texto or "monto" in texto:
        destinatario = "Dirección del Centro / Vicerrectoría de Investigación"
    elif "experticia" in texto or "equipo" in texto:
        destinatario = "Dirección del Centro"

    return _json(
        {
            "ok": True,
            "accion": "escalado",
            "destinatario": destinatario,
            "convocatoria_id": convocatoria_id,
            "motivo": motivo,
            "analisis_realizado": analisis_realizado or [],
            "brechas": brechas or [],
            "preguntas_pendientes": preguntas_pendientes or [],
            "nota": "No se creó solicitud ni se asignó equipo. La decisión queda en manos humanas.",
        }
    )
