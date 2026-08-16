"""Acceso a la base de conocimiento **pública**.

Las convocatorias y las políticas viven como documentos markdown con
frontmatter YAML en `base_conocimiento/`. Este módulo los carga, los indexa y
permite buscarlos y leerlos.

Es información pública: nada de lo que hay aquí requiere autenticación. La
frontera entre lo público y lo interno es justamente que este módulo no conoce
usuarios, sesiones ni roles — eso vive en `centro.internos`.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE_CONOCIMIENTO = ROOT / "base_conocimiento"
DIR_CONVOCATORIAS = BASE_CONOCIMIENTO / "convocatorias"
DIR_POLITICAS = BASE_CONOCIMIENTO / "politicas"


@dataclass(frozen=True)
class Documento:
    """Un documento de la base de conocimiento: metadatos + texto completo."""

    ruta: Path
    meta: dict
    cuerpo: str

    @property
    def id(self) -> str:
        return str(self.meta.get("id", self.ruta.stem))

    @property
    def titulo(self) -> str:
        return str(self.meta.get("titulo", self.ruta.stem))

    @property
    def texto_busqueda(self) -> str:
        """Metadatos y cuerpo concatenados en minúsculas, para búsqueda libre."""
        metadatos = " ".join(str(v) for v in self.meta.values())
        return f"{metadatos}\n{self.cuerpo}".lower()


def _partir_frontmatter(texto: str) -> tuple[dict, str]:
    """Separa el frontmatter YAML del cuerpo markdown.

    Un documento sin frontmatter no es un error: se trata como cuerpo puro con
    metadatos vacíos, para que agregar un archivo suelto no rompa la carga.
    """
    if not texto.startswith("---"):
        return {}, texto
    partes = texto.split("---", 2)
    if len(partes) < 3:
        return {}, texto
    meta = yaml.safe_load(partes[1]) or {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, partes[2].strip()


def _cargar_directorio(directorio: Path) -> tuple[Documento, ...]:
    documentos = []
    for ruta in sorted(directorio.glob("*.md")):
        meta, cuerpo = _partir_frontmatter(ruta.read_text(encoding="utf-8"))
        documentos.append(Documento(ruta=ruta, meta=meta, cuerpo=cuerpo))
    return tuple(documentos)


@lru_cache(maxsize=1)
def convocatorias() -> tuple[Documento, ...]:
    return _cargar_directorio(DIR_CONVOCATORIAS)


@lru_cache(maxsize=1)
def politicas() -> tuple[Documento, ...]:
    return _cargar_directorio(DIR_POLITICAS)


def buscar_convocatorias(
    area: Optional[str] = None,
    tipo: Optional[str] = None,
    texto: Optional[str] = None,
) -> list[Documento]:
    """Filtra convocatorias abiertas por área, tipo y/o texto libre.

    Los tres filtros son opcionales y se combinan con AND. Sin filtros devuelve
    todas las convocatorias abiertas.
    """
    resultado = []
    for doc in convocatorias():
        if str(doc.meta.get("estado", "abierta")) != "abierta":
            continue
        if area and area.lower() not in str(doc.meta.get("area", "")).lower():
            continue
        if tipo and tipo.lower() not in str(doc.meta.get("tipo", "")).lower():
            continue
        if texto and texto.lower() not in doc.texto_busqueda:
            continue
        resultado.append(doc)
    return resultado


def obtener_convocatoria(convocatoria_id: str) -> Optional[Documento]:
    """Busca por id exacto y, si no hay, por coincidencia parcial en el id."""
    objetivo = convocatoria_id.strip().upper()
    for doc in convocatorias():
        if doc.id.upper() == objetivo:
            return doc
    for doc in convocatorias():
        if objetivo in doc.id.upper():
            return doc
    return None


def buscar_politica(tema: str) -> Optional[Documento]:
    """Encuentra la política más relevante para un tema.

    Puntúa primero por coincidencia en el campo `tema` del frontmatter (que es
    la lista de sinónimos con que el equipo nombra cada política) y solo después
    por aparición en el cuerpo. Así "overhead" llega a la política financiera
    aunque la palabra también aparezca de pasada en otro documento.
    """
    consulta = tema.lower().strip()
    palabras = [p for p in consulta.replace(",", " ").split() if len(p) > 3]

    mejor: Optional[Documento] = None
    mejor_puntaje = 0
    for doc in politicas():
        etiquetas = str(doc.meta.get("tema", "")).lower()
        titulo = doc.titulo.lower()
        puntaje = 0
        if consulta and consulta in etiquetas:
            puntaje += 10
        for palabra in palabras:
            if palabra in etiquetas:
                puntaje += 5
            if palabra in titulo:
                puntaje += 3
            if palabra in doc.cuerpo.lower():
                puntaje += 1
        if puntaje > mejor_puntaje:
            mejor, mejor_puntaje = doc, puntaje
    return mejor


def limpiar_cache() -> None:
    """Vacía el cache de documentos. Útil en tests que modifican la base."""
    convocatorias.cache_clear()
    politicas.cache_clear()
