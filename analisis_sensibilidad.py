# -*- coding: utf-8 -*-
"""
================================================================================
 ANALISIS DE SENSIBILIDAD (grilla de parametros)
 Tesina Finanzas Computacionales - UCEMA - Matias Dean
================================================================================

 Varia UN parametro por vez alrededor de la configuracion base y mide como
 cambian Sharpe, CAGR, volatilidad, max drawdown y cantidad de operaciones.
 Todas las corridas se miden sobre la MISMA ventana (para que sean comparables).

 Base: Donchian 20 | Momentum 252 | diario | margen +0,3% | permanencia Top 5 | costo 0,20%

 Requiere momentum_dual.py y datos_historicos.csv en la misma carpeta.
================================================================================
"""

import numpy as np
import pandas as pd
import momentum_dual as md

ARCHIVO_CSV = "datos_historicos.csv"
S = md.SECTORES
REF = md.REFUGIO
BM = md.BENCHMARK

# --- base ---
BASE = dict(don=20, mom=252, freq="diario", margen=0.003, permanencia=5, costo=0.0020)

# cargar datos una vez
_df = pd.read_csv(ARCHIVO_CSV, index_col=0, parse_dates=True)
_datos = md._separar(_df)
_ret_ap = _datos["apertura"].pct_change(fill_method=None)
_ret_ap[REF] = _datos["ref_o"].pct_change(fill_method=None)
_ret_spy = _datos["spy_c"].pct_change(fill_method=None)

# ventana COMUN para todas las corridas: descontar el peor calentamiento posible
# (momentum mas largo 252 + donchian mas largo 100 = 352 ruedas)
_idx = _datos["cierre"].index
INI = _idx[252 + 100]
FIN = _idx[-1]


def run(don, mom, freq, margen, permanencia, costo):
    """Corre una configuracion y devuelve (stats, n_operaciones)."""
    md.VENTANA_DON = don
    md.VENTANA_MOM = mom
    md.MARGEN_RUPTURA = margen
    md.RANK_SALIDA = permanencia
    md.COSTO = costo
    pesos = md.construir_pesos(_datos["cierre"], _datos["high"], _datos["low"])
    pesos = md.aplicar_frecuencia(pesos, freq)
    r = md.retorno_cartera(pesos, _ret_ap).loc[INI:FIN]
    s = md.stats_raw(r)
    turn = pesos.loc[INI:FIN].diff().abs().sum(axis=1)
    nops = int((turn > 1e-6).sum())
    expo = pesos[S].sum(axis=1).loc[INI:FIN].mean()
    return s, nops, expo


def fila(nombre, s, nops, expo):
    return {"Configuracion": nombre,
            "Expo. acc.": f"{expo:.0%}",
            "CAGR": f"{s['cagr']:.1%}",
            "Vol": f"{s['vol']:.1%}",
            "Sharpe": round(s['sharpe'], 2),
            "Sortino": round(s['sortino'], 2),
            "Max DD": f"{s['maxdd']:.1%}",
            "Calmar": round(s['calmar'], 2),
            "N oper.": nops}


def grilla(nombre_param, valores, clave):
    """Varia un parametro (clave) sobre 'valores', dejando el resto en base."""
    print(f"\n{'='*86}\n  SENSIBILIDAD A: {nombre_param}\n{'='*86}")
    filas = []
    for v in valores:
        cfg = dict(BASE); cfg[clave] = v
        s, nops, expo = run(**cfg)
        etiqueta = f"{nombre_param} = {v}" + ("  (BASE)" if v == BASE[clave] else "")
        filas.append(fila(etiqueta, s, nops, expo))
    tab = pd.DataFrame(filas).set_index("Configuracion")
    print(tab.to_string())
    return tab


def main():
    # referencia SPY sobre la misma ventana
    s_spy = md.stats_raw(_ret_spy.loc[INI:FIN])
    print("="*86)
    print(f"  GRILLA DE SENSIBILIDAD  |  ventana comun {INI.date()} -> {FIN.date()}")
    print(f"  Referencia SPY Buy&Hold: CAGR {s_spy['cagr']:.1%} | Sharpe {s_spy['sharpe']:.2f} | MaxDD {s_spy['maxdd']:.1%}")
    print("="*86)

    tablas = {}
    tablas["Donchian"]     = grilla("Ventana Donchian (dias)", [20, 50, 100], "don")
    tablas["Momentum"]     = grilla("Ventana Momentum (dias)", [63, 126, 252], "mom")
    tablas["Frecuencia"]   = grilla("Frecuencia rebalanceo", ["diario", "semanal", "mensual"], "freq")
    tablas["Margen"]       = grilla("Margen de ruptura", [0.0, 0.003, 0.01], "margen")
    tablas["Permanencia"]  = grilla("Banda permanencia (puesto)", [5, 6, 7], "permanencia")
    tablas["Costo"]        = grilla("Costo por operacion", [0.0, 0.002, 0.005], "costo")

    # guardar todo a Excel (una hoja por parametro)
    try:
        with pd.ExcelWriter("analisis_sensibilidad.xlsx", engine="openpyxl") as xw:
            ref = pd.DataFrame([fila("SPY Buy & Hold", s_spy, 0, 1.0)]).set_index("Configuracion")
            ref.to_excel(xw, sheet_name="Referencia SPY")
            for nombre, tab in tablas.items():
                tab.to_excel(xw, sheet_name=nombre[:31])
        print("\n  Guardado: analisis_sensibilidad.xlsx (una hoja por parametro)")
    except Exception as e:
        print(f"\n  (No se pudo escribir el Excel: {e})")

    # restaurar base por las dudas
    md.VENTANA_DON, md.VENTANA_MOM = BASE["don"], BASE["mom"]
    md.MARGEN_RUPTURA, md.RANK_SALIDA, md.COSTO = BASE["margen"], BASE["permanencia"], BASE["costo"]


if __name__ == "__main__":
    main()
