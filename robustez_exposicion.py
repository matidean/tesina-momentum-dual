# -*- coding: utf-8 -*-
"""
================================================================================
 ROBUSTEZ Y COMPARADORES DE EXPOSICION (registro de motivos)
 Tesina Finanzas Computacionales - UCEMA - Matias Dean
================================================================================

 Reutiliza la logica del archivo principal (momentum_dual.py) y agrega:

  A) REGISTRO DE MOTIVOS: por cada entrada/salida de un sector, anota QUE senal
     la disparo (ruptura del techo de Donchian, ruptura del piso, o caida del
     ranking). Sale a Excel para poder auditar cada movimiento.

  B) COMPARADOR DE EXPOSICION: contrasta la estrategia completa contra variantes
     con exposicion parecida PERO sin el filtro, para ver si los filtros aportan
     algo mas que simplemente tener menos capital en acciones.

 Pensado para correrse con el mismo datos_historicos.csv ya congelado.
================================================================================
"""

import numpy as np
import pandas as pd
import momentum_dual as md   # reutiliza _separar, retorno_cartera, stats_raw, etc.

ARCHIVO_CSV = "datos_historicos.csv"
S = md.SECTORES
REF = md.REFUGIO       # BIL
BM = md.BENCHMARK      # SPY
W = 1.0 / md.N_SLOTS


# ==============================================================================
#  A) CONSTRUCCION DE PESOS CON REGISTRO DE MOTIVOS
# ==============================================================================

def construir_pesos_con_motivos(cierre, high, low):
    """
    Igual que momentum_dual.construir_pesos, pero ademas devuelve un registro
    (lista de eventos) con el MOTIVO de cada entrada y salida.
    Devuelve: (pesos, eventos_df)
    """
    momentum = cierre.pct_change(md.VENTANA_MOM, fill_method=None)
    don_sup = high.rolling(md.VENTANA_DON).max().shift(1)
    don_inf = low.rolling(md.VENTANA_DON).min().shift(1)
    ranking = momentum.rank(axis=1, ascending=False)

    columnas = list(cierre.columns) + [REF]
    pesos = pd.DataFrame(0.0, index=cierre.index, columns=columnas)
    en_cartera = []
    eventos = []

    for i, fecha in enumerate(cierre.index):
        m = momentum.iloc[i]
        rk = ranking.iloc[i]
        sup = don_sup.iloc[i]
        inf = don_inf.iloc[i]
        px = cierre.iloc[i]

        # --- 1) SALIDAS, anotando el motivo ---
        siguen = []
        for s in en_cartera:
            if pd.isna(rk[s]):
                eventos.append({"Fecha": fecha.date(), "Activo": s, "Accion": "SALE",
                                "Motivo": "sin dato de ranking", "Rank": np.nan,
                                "Momentum_12m": np.nan, "Cierre": round(float(px[s]), 2),
                                "Donchian_inf": np.nan})
                continue
            rompe_abajo = pd.notna(inf[s]) and px[s] < inf[s]
            fuera_ranking = rk[s] > md.RANK_SALIDA
            if not rompe_abajo and not fuera_ranking:
                siguen.append(s)
            else:
                if rompe_abajo and fuera_ranking:
                    motivo = "ruptura piso Donchian + cae del ranking (>#%d)" % md.RANK_SALIDA
                elif rompe_abajo:
                    motivo = "ruptura piso Donchian"
                else:
                    motivo = "cae del ranking (>#%d)" % md.RANK_SALIDA
                eventos.append({"Fecha": fecha.date(), "Activo": s, "Accion": "SALE",
                                "Motivo": motivo, "Rank": int(rk[s]),
                                "Momentum_12m": round(float(m[s]), 4) if pd.notna(m[s]) else np.nan,
                                "Cierre": round(float(px[s]), 2),
                                "Donchian_inf": round(float(inf[s]), 2) if pd.notna(inf[s]) else np.nan})
        en_cartera = siguen

        # --- 2) ENTRADAS, anotando el motivo ---
        if len(en_cartera) < md.N_SLOTS:
            candidatos = m.dropna().sort_values(ascending=False)
            for s in candidatos.index:
                if len(en_cartera) >= md.N_SLOTS:
                    break
                if s in en_cartera or rk[s] > md.RANK_ENTRADA:
                    continue
                rompe_arriba = pd.notna(sup[s]) and px[s] > sup[s] * (1 + md.MARGEN_RUPTURA)
                if rompe_arriba:
                    en_cartera.append(s)
                    eventos.append({"Fecha": fecha.date(), "Activo": s, "Accion": "ENTRA",
                                    "Motivo": "ruptura techo Donchian +%.1f%% & Top %d"
                                              % (md.MARGEN_RUPTURA * 100, md.RANK_ENTRADA),
                                    "Rank": int(rk[s]),
                                    "Momentum_12m": round(float(m[s]), 4),
                                    "Cierre": round(float(px[s]), 2),
                                    "Donchian_inf": round(float(sup[s]), 2) if pd.notna(sup[s]) else np.nan})

        for s in en_cartera:
            pesos.at[fecha, s] = W
        pesos.at[fecha, REF] = (md.N_SLOTS - len(en_cartera)) * W

    eventos_df = pd.DataFrame(eventos)
    # renombrar la ultima columna segun accion seria lioso; la dejamos como ref Donchian
    eventos_df = eventos_df.rename(columns={"Donchian_inf": "Donchian_ref"})
    return pesos, eventos_df


# ==============================================================================
#  B) VARIANTES / COMPARADORES
# ==============================================================================

def pesos_top3_sin_filtro(cierre):
    """
    Variante 'Top 3 sin filtro': cada dia invierte 33,3% en cada uno de los 3
    sectores con mayor momentum. SIN Donchian y SIN refugio (siempre 100%
    invertido). Solo va a BIL si hay menos de 3 sectores con momentum valido.
    """
    momentum = cierre.pct_change(md.VENTANA_MOM, fill_method=None)
    columnas = list(cierre.columns) + [REF]
    pesos = pd.DataFrame(0.0, index=cierre.index, columns=columnas)
    for i, fecha in enumerate(cierre.index):
        top = momentum.iloc[i].dropna().sort_values(ascending=False).head(md.N_SLOTS).index
        for s in top:
            pesos.at[fecha, s] = W
        pesos.at[fecha, REF] = (md.N_SLOTS - len(top)) * W
    return pesos


def pesos_exposicion_replicada(pesos_estrategia):
    """
    Variante 'exposicion similar dinamica': cada dia toma la MISMA fraccion en
    acciones que tuvo la estrategia, pero la coloca en el mercado (SPY) en vez
    de en los sectores filtrados. El resto va a BIL. Misma exposicion diaria,
    sin seleccion ni timing de sector.
    """
    equity_frac = pesos_estrategia[S].sum(axis=1)   # % en acciones cada dia
    pesos = pd.DataFrame(0.0, index=pesos_estrategia.index, columns=[BM, REF])
    pesos[BM] = equity_frac
    pesos[REF] = 1.0 - equity_frac
    return pesos


def pesos_mezcla_estatica(index, frac_equity):
    """
    Variante 'exposicion promedio estatica': fraccion fija en SPY y el resto en
    BIL, constante todos los dias (ej. 66,5% SPY / 33,5% BIL).
    """
    pesos = pd.DataFrame(0.0, index=index, columns=[BM, REF])
    pesos[BM] = frac_equity
    pesos[REF] = 1.0 - frac_equity
    return pesos


# ==============================================================================
#  MAIN
# ==============================================================================

def main():
    df = pd.read_csv(ARCHIVO_CSV, index_col=0, parse_dates=True)
    datos = md._separar(df)

    # matriz de retornos APERTURA-a-apertura, con sectores + BIL + SPY
    ret_ap = datos["apertura"].pct_change(fill_method=None)
    ret_ap[REF] = datos["ref_o"].pct_change(fill_method=None)
    ret_ap[BM] = datos["spy_o"].pct_change(fill_method=None)
    ret_spy_cc = datos["spy_c"].pct_change(fill_method=None)   # SPY buy&hold cierre-a-cierre

    # --- estrategia completa (con registro de motivos) ---
    pesos_base, eventos = construir_pesos_con_motivos(datos["cierre"], datos["high"], datos["low"])

    # chequeo de equivalencia con la funcion original (deben dar identicos)
    pesos_orig = md.construir_pesos(datos["cierre"], datos["high"], datos["low"])
    iguales = np.allclose(pesos_base.values, pesos_orig.values, atol=1e-9)
    print("Chequeo: pesos con motivos == construir_pesos original?", iguales)

    ret_base = md.retorno_cartera(pesos_base, ret_ap)

    # --- variantes ---
    pesos_c1 = pesos_top3_sin_filtro(datos["cierre"])
    ret_c1 = md.retorno_cartera(pesos_c1, ret_ap)

    pesos_c2 = pesos_exposicion_replicada(pesos_base)
    ret_c2 = md.retorno_cartera(pesos_c2, ret_ap)

    ini = pesos_base.index[md.VENTANA_MOM + md.VENTANA_DON]
    frac_prom = pesos_base[S].sum(axis=1).loc[ini:].mean()   # exposicion media EN LA VENTANA
    pesos_c3 = pesos_mezcla_estatica(datos["cierre"].index, frac_prom)
    ret_c3 = md.retorno_cartera(pesos_c3, ret_ap)

    # --- ventana de analisis (igual que el backtest base) ---
    fin = pesos_base.index[-1]

    def expo(pesos):
        return pesos[S].sum(axis=1).loc[ini:fin].mean() if any(c in pesos.columns for c in S) else \
               pesos[BM].loc[ini:fin].mean()

    series = [
        ("SPY (Buy & Hold)", ret_spy_cc, 1.00),
        ("Estrategia completa", ret_base, pesos_base[S].sum(axis=1).loc[ini:fin].mean()),
        ("Top 3 sin filtro (siempre invertido)", ret_c1, pesos_c1[S].sum(axis=1).loc[ini:fin].mean()),
        ("Exposicion similar dinamica (en SPY)", ret_c2, pesos_c2[BM].loc[ini:fin].mean()),
        (f"Exposicion estatica {frac_prom:.0%} SPY / {1-frac_prom:.0%} BIL", ret_c3, pesos_c3[BM].loc[ini:fin].mean()),
    ]

    filas = []
    for nombre, r, exp_eq in series:
        s = md.stats_raw(r.loc[ini:fin])
        fila = md.fila_formateada(nombre, s)
        fila["Expo. acciones"] = f"{exp_eq:.0%}"
        filas.append(fila)
    tabla = pd.DataFrame(filas).set_index("Estrategia")
    cols = ["Expo. acciones", "Ret. total", "CAGR", "Volatilidad", "Sharpe", "Sortino", "Max Drawdown", "Calmar"]
    tabla = tabla[cols]

    print("\n" + "=" * 92)
    print("  COMPARADOR DE EXPOSICION  |  periodo", ini.date(), "->", fin.date())
    print("=" * 92)
    print(tabla.to_string())
    print("=" * 92)

    # --- resumen de motivos de las ordenes ---
    ev = eventos.copy()
    ev_v = ev[pd.to_datetime(ev["Fecha"]) >= ini]
    print("\n  MOTIVOS DE LAS ORDENES (en la ventana de analisis):")
    salidas = ev_v[ev_v["Accion"] == "SALE"]
    entradas = ev_v[ev_v["Accion"] == "ENTRA"]
    print(f"  Total entradas: {len(entradas)}  |  Total salidas: {len(salidas)}")
    print("\n  Salidas por motivo:")
    print(salidas["Motivo"].value_counts().to_string())

    # --- guardar CSV ---
    tabla.to_csv("comparador_exposicion.csv")
    ev.to_csv("motivos_senales.csv", index=False)

    # --- guardar Excel con 3 hojas (comparador, resumen motivos, detalle) ---
    resumen_mot = pd.concat([
        pd.DataFrame({"Motivo": ["--- ENTRADAS ---"], "Cantidad": [len(entradas)]}),
        entradas["Motivo"].value_counts().rename_axis("Motivo").reset_index(name="Cantidad"),
        pd.DataFrame({"Motivo": ["--- SALIDAS ---"], "Cantidad": [len(salidas)]}),
        salidas["Motivo"].value_counts().rename_axis("Motivo").reset_index(name="Cantidad"),
    ], ignore_index=True)
    try:
        with pd.ExcelWriter("robustez_exposicion.xlsx", engine="openpyxl") as xw:
            tabla.reset_index().to_excel(xw, sheet_name="Comparador exposicion", index=False)
            resumen_mot.to_excel(xw, sheet_name="Motivos resumen", index=False)
            ev.to_excel(xw, sheet_name="Motivos detalle", index=False)
        print("\n  Guardado: comparador_exposicion.csv | motivos_senales.csv | robustez_exposicion.xlsx")
    except Exception as e:
        print(f"\n  (No se pudo escribir el Excel: {e}. Quedan los CSV igual.)")

    return tabla, ev, salidas


if __name__ == "__main__":
    main()
