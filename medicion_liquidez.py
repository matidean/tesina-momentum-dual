# -*- coding: utf-8 -*-
"""
================================================================================
 MEDICION DE LIQUIDEZ DEL UNIVERSO
 Tesina Finanzas Computacionales - UCEMA - Matias Dean
================================================================================

 Baja el volumen diario de Yahoo Finance y calcula, para cada ETF, el volumen
 promedio diario operado EN DOLARES (precio de cierre x cantidad de acciones).
 Asi la liquidez deja de ser un supuesto y pasa a estar medida con un numero.

 Se corre una vez; genera 'liquidez_etfs.csv' y muestra la tabla en pantalla.
================================================================================
"""

import pandas as pd

# --- universo (mismos tickers que la estrategia) ---
SECTORES = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY",
            "XLP", "XLB", "XLU", "XLRE", "XLC"]
REFUGIO  = "BIL"
BENCHMARK = "SPY"
TODOS = SECTORES + [REFUGIO, BENCHMARK]

INICIO = "2016-01-01"
FIN = None   # None = hasta hoy


def bajar_ohlcv(tickers, start, end):
    """Baja Cierre y Volumen diarios desde Yahoo Finance."""
    import yfinance as yf
    data = yf.download(tickers, start=start, end=end,
                       auto_adjust=True, progress=False)
    cierre = data["Close"].copy()
    volumen = data["Volume"].copy()
    if isinstance(cierre, pd.Series):      # por si baja un solo ticker
        cierre = cierre.to_frame(tickers[0]); volumen = volumen.to_frame(tickers[0])
    return cierre, volumen


def main():
    print("Bajando cierre y volumen de Yahoo Finance...")
    cierre, volumen = bajar_ohlcv(TODOS, INICIO, FIN)

    # volumen operado en DOLARES cada dia = precio de cierre x acciones operadas
    dolar_vol = (cierre * volumen)

    # ventanas: todo el periodo y el ultimo anio (252 ruedas)
    filas = []
    for t in TODOS:
        if t not in dolar_vol.columns:
            continue
        serie = dolar_vol[t].dropna()
        if len(serie) == 0:
            continue
        prom_total = serie.mean()
        prom_1y = serie.tail(252).mean()
        minimo = serie.tail(252).min()
        filas.append({
            "ETF": t,
            "Vol. diario prom. (USD, todo el periodo)": prom_total,
            "Vol. diario prom. (USD, ultimo anio)": prom_1y,
            "Dia menos liquido ult. anio (USD)": minimo,
        })

    tabla = pd.DataFrame(filas)
    # ordenar por liquidez del ultimo anio, de mayor a menor
    tabla = tabla.sort_values("Vol. diario prom. (USD, ultimo anio)", ascending=False)

    # version legible (en millones de USD)
    legible = tabla.copy()
    for c in legible.columns:
        if c != "ETF":
            legible[c] = (legible[c] / 1e6).round(1).astype(str) + " M"

    print("\n" + "=" * 80)
    print("  VOLUMEN DIARIO PROMEDIO OPERADO (en millones de USD)")
    print("=" * 80)
    print(legible.to_string(index=False))
    print("=" * 80)

    # guardar: una version con numeros crudos y otra legible
    tabla.to_csv("liquidez_etfs.csv", index=False)
    legible.to_csv("liquidez_etfs_legible.csv", index=False)
    print("\nGuardado: liquidez_etfs.csv (numeros crudos) | liquidez_etfs_legible.csv (en millones)")

    # resumen para el texto
    menos_liquido = tabla.iloc[-1]
    print(f"\nPara el texto: el ETF menos liquido del universo es "
          f"{menos_liquido['ETF']}, con un volumen diario promedio de "
          f"USD {menos_liquido['Vol. diario prom. (USD, ultimo anio)']/1e6:.0f} millones "
          f"en el ultimo anio.")


if __name__ == "__main__":
    main()
