from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "datos_energia.csv"
DEMAND_COL = "AT_load_actual_entsoe_transparency"


@lru_cache(maxsize=1)
def load_energy_frame() -> pd.DataFrame:
    data = pd.read_csv(CSV_PATH)
    data["time"] = pd.to_datetime(data["time"])
    return data.set_index("time").sort_index()


def slice_range(start: str, end: str) -> pd.DataFrame:
    frame = load_energy_frame()
    start_ts = pd.to_datetime(start, errors="coerce")
    end_ts = pd.to_datetime(end, errors="coerce")
    if pd.isna(start_ts) or pd.isna(end_ts):
        raise ValueError(
            "Fechas inválidas. Use ISO, por ejemplo '2019-08-01' o '2019-08-01 12:00'."
        )
    if start_ts > end_ts:
        raise ValueError("La fecha inicial no puede ser posterior a la fecha final.")
    window = frame.loc[start_ts:end_ts]
    if window.empty:
        raise ValueError(
            f"No hay registros entre {start_ts} y {end_ts}. "
            f"Rango disponible: {frame.index.min()} — {frame.index.max()}."
        )
    return window
