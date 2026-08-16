from __future__ import annotations

import json
from typing import Annotated

from pydantic import Field

from energia.data import DEMAND_COL, slice_range


def consultar_demanda(
    start: Annotated[str, Field(description="Fecha/hora inicial ISO, p.ej. 2019-08-01")],
    end: Annotated[str, Field(description="Fecha/hora final ISO, p.ej. 2019-08-07")],
) -> str:
    """Estadísticas de demanda real (MW) en un intervalo horario.

    Lee el dataset ENTSO-E de Austria. Si el intervalo es inválido o no hay
    observaciones, devuelve un JSON de error utilizable por el agente.
    """
    try:
        window = slice_range(start, end)
        series = window[DEMAND_COL].dropna()
        if series.empty:
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        "El intervalo no tiene demanda real observada "
                        "(solo hay pronóstico o valores vacíos)."
                    ),
                },
                ensure_ascii=False,
            )
        payload = {
            "ok": True,
            "start": str(series.index.min()),
            "end": str(series.index.max()),
            "n_hours": int(series.count()),
            "mean_mw": round(float(series.mean()), 2),
            "min_mw": round(float(series.min()), 2),
            "max_mw": round(float(series.max()), 2),
        }
        return json.dumps(payload, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


def consultar_pronostico(
    start: Annotated[str, Field(description="Fecha/hora inicial ISO del tramo a evaluar")],
    end: Annotated[str, Field(description="Fecha/hora final ISO del tramo a evaluar")],
) -> str:
    """Compara pronóstico vs demanda real y reporta MAE cuando ambos existen."""
    try:
        window = slice_range(start, end)
        forecast = window["forecast"].dropna()
        if forecast.empty:
            return json.dumps(
                {
                    "ok": False,
                    "error": "El intervalo no contiene valores de pronóstico.",
                },
                ensure_ascii=False,
            )
        both = window[[DEMAND_COL, "forecast"]].dropna()
        payload = {
            "ok": True,
            "n_forecast_hours": int(forecast.count()),
            "forecast_mean_mw": round(float(forecast.mean()), 2),
            "forecast_min_mw": round(float(forecast.min()), 2),
            "forecast_max_mw": round(float(forecast.max()), 2),
        }
        if both.empty:
            payload["mae_mw"] = None
            payload["note"] = (
                "No hay horas con demanda real y pronóstico a la vez; "
                "se reporta solo el pronóstico."
            )
        else:
            mae = (both[DEMAND_COL] - both["forecast"]).abs().mean()
            payload["mae_mw"] = round(float(mae), 2)
            payload["n_paired_hours"] = int(len(both))
            payload["actual_mean_mw"] = round(float(both[DEMAND_COL].mean()), 2)
        return json.dumps(payload, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


def detectar_picos(
    start: Annotated[str, Field(description="Fecha/hora inicial ISO")],
    end: Annotated[str, Field(description="Fecha/hora final ISO")],
    n: Annotated[int, Field(description="Cantidad de picos a devolver (1 a 24)")] = 5,
) -> str:
    """Devuelve las n horas de mayor demanda real en el intervalo."""
    try:
        if n < 1 or n > 24:
            return json.dumps(
                {"ok": False, "error": "El parámetro n debe estar entre 1 y 24."},
                ensure_ascii=False,
            )
        window = slice_range(start, end)
        series = window[DEMAND_COL].dropna()
        if series.empty:
            return json.dumps(
                {"ok": False, "error": "No hay demanda real para detectar picos."},
                ensure_ascii=False,
            )
        top = series.nlargest(n)
        peaks = [
            {"time": str(ts), "mw": round(float(value), 2)}
            for ts, value in top.items()
        ]
        return json.dumps({"ok": True, "peaks": peaks}, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
