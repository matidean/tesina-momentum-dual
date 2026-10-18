# -*- coding: utf-8 -*-
"""
================================================================================
 ANALISIS CRITICO (filtro clasico, regimen, captura, minimo de tenencia, whipsaw)
 Tesina Finanzas Computacionales - UCEMA - Matias Dean
================================================================================

 Cubre los tres "proximos ajustes" que faltaban:

  A) Filtro de momentum absoluto CLASICO (Antonacci): reemplaza el canal de
     Donchian por "retorno propio 12m > retorno del refugio 12m".
  B) Desempeño por REGIMEN de mercado: como se comporto la estrategia durante
     las caidas de 2018, 2020 y 2022 frente al resto (fases alcistas).
  C) Periodo minimo de tenencia: no permitir vender una posicion antes de N
     ruedas, para ver si frenar la rotacion mejora el resultado.

 Requiere momentum_dual.py y datos_historicos.csv en la misma carpeta.
================================================================================
"""

import numpy as np
import pandas as pd
import momentum_dual as md
from robustez_exposicion import construir_pesos_con_motivos   # para el registro de motivos

ARCHIVO_CSV = "datos_historicos.csv"
S = md.SECTORES
REF = md.REFUGIO
BM = md.BENCHMARK
W = 1.0 / md.N_SLOTS

_df = pd.read_csv(ARCHIVO_CSV, index_col=0, parse_dates=True)
D = md._separar(_df)
RET_AP = D["apertura"].pct_change(fill_method=None)
RET_AP[REF] = D["ref_o"].pct_change(fill_method=None)
RET_AP[BM] = D["spy_o"].pct_change(fill_method=None)
RET_SPY = D["spy_c"].pct_change(fill_method=None)
IDX = D["cierre"].index
INI = IDX[md.VENTANA_MOM + md.VENTANA_DON]
FIN = IDX[-1]


def _fila(nombre, s, expo=None):
    d = {"Variante": nombre, "CAGR": f"{s['cagr']:.1%}", "Vol": f"{s['vol']:.1%}",
         "Sharpe": round(s['sharpe'], 2), "Sortino": round(s['sortino'], 2),
         "Max DD": f"{s['maxdd']:.1%}", "Calmar": round(s['calmar'], 2)}
    if expo is not None:
        d["Expo. acc."] = f"{expo:.0%}"
    return d


# ==============================================================================
#  A) FILTRO DE MOMENTUM ABSOLUTO CLASICO (Antonacci) - sin Donchian
# ==============================================================================

def pesos_abs_clasico(cierre, ref_c):
    """
    Top 3 por fuerza relativa (igual que siempre), pero el filtro absoluto NO es
    Donchian: un sector del Top 3 entra solo si su retorno propio de 252 dias
    supera al retorno del refugio (BIL) en esos mismos 252 dias. Si no, ese
    tramo va a BIL. Es el momentum absoluto clasico del libro de Antonacci.
    """
    momentum = cierre.pct_change(md.VENTANA_MOM, fill_method=None)
    ret_ref = ref_c.pct_change(md.VENTANA_MOM, fill_method=None)
    columnas = list(cierre.columns) + [REF]
    pesos = pd.DataFrame(0.0, index=cierre.index, columns=columnas)
    for i, fecha in enumerate(cierre.index):
        m = momentum.iloc[i].dropna()
        if len(m) == 0:
            pesos.at[fecha, REF] = 1.0
            continue
        top = m.sort_values(ascending=False).head(md.N_SLOTS).index
        umbral = ret_ref.iloc[i]
        usados = 0
        for s in top:
            if pd.notna(umbral) and m[s] > umbral:   # gana por si mismo vs refugio
                pesos.at[fecha, s] = W
                usados += 1
        pesos.at[fecha, REF] = (md.N_SLOTS - usados) * W
    return pesos


# ==============================================================================
#  C) PERIODO MINIMO DE TENENCIA (variante del filtro Donchian)
# ==============================================================================

def pesos_con_min_hold(cierre, high, low, dias_min):
    """
    Igual que la estrategia base (Donchian + permanencia + margen), pero una
    posicion NO se puede vender antes de 'dias_min' ruedas desde que entro,
    aunque se gatille una senal de salida. Frena la rotacion de corto plazo.
    """
    momentum = cierre.pct_change(md.VENTANA_MOM, fill_method=None)
    don_sup = high.rolling(md.VENTANA_DON).max().shift(1)
    don_inf = low.rolling(md.VENTANA_DON).min().shift(1)
    ranking = momentum.rank(axis=1, ascending=False)
    columnas = list(cierre.columns) + [REF]
    pesos = pd.DataFrame(0.0, index=cierre.index, columns=columnas)
    en_cartera = []
    dias_en = {}   # cuantas ruedas lleva cada posicion

    for i, fecha in enumerate(cierre.index):
        m = momentum.iloc[i]; rk = ranking.iloc[i]
        sup = don_sup.iloc[i]; inf = don_inf.iloc[i]; px = cierre.iloc[i]

        siguen = []
        for s in en_cartera:
            dias_en[s] = dias_en.get(s, 0) + 1
            if pd.isna(rk[s]):
                continue
            rompe_abajo = pd.notna(inf[s]) and px[s] < inf[s]
            fuera_ranking = rk[s] > md.RANK_SALIDA
            quiere_salir = rompe_abajo or fuera_ranking
            # bloqueo: si no cumplio el minimo de tenencia, se queda igual
            if quiere_salir and dias_en[s] < dias_min:
                quiere_salir = False
            if not quiere_salir:
                siguen.append(s)
            else:
                dias_en.pop(s, None)
        en_cartera = siguen

        if len(en_cartera) < md.N_SLOTS:
            for s in m.dropna().sort_values(ascending=False).index:
                if len(en_cartera) >= md.N_SLOTS:
                    break
                if s in en_cartera or rk[s] > md.RANK_ENTRADA:
                    continue
                if pd.notna(sup[s]) and px[s] > sup[s] * (1 + md.MARGEN_RUPTURA):
                    en_cartera.append(s); dias_en[s] = 0

        for s in en_cartera:
            pesos.at[fecha, s] = W
        pesos.at[fecha, REF] = (md.N_SLOTS - len(en_cartera)) * W
    return pesos


def _nops(pesos):
    turn = pesos.loc[INI:FIN].diff().abs().sum(axis=1)
    return int((turn > 1e-6).sum())


# ==============================================================================
#  B) DESEMPEÑO POR REGIMEN DE MERCADO
# ==============================================================================

EPISODIOS = [
    ("Corrección Q4 2018", "2018-09-20", "2018-12-24"),
    ("Crash COVID 2020", "2020-02-19", "2020-03-23"),
    ("Bear 2022", "2022-01-03", "2022-10-12"),
]

def analisis_regimen(ret_est):
    filas = []
    for nombre, a, b in EPISODIOS:
        re = ret_est.loc[a:b]; rs = RET_SPY.loc[a:b]
        tot_e = (1 + re).prod() - 1
        tot_s = (1 + rs).prod() - 1
        filas.append({"Episodio": nombre, "Desde": a, "Hasta": b,
                      "Estrategia": f"{tot_e:+.1%}", "SPY": f"{tot_s:+.1%}",
                      "Proteccion (pp)": f"{(tot_e - tot_s)*100:+.1f}"})
    return pd.DataFrame(filas)

def captura(ret_est):
    """Captura en dias de estres (SPY en drawdown > 10%) vs dias de calma."""
    curva = (1 + RET_SPY.loc[INI:FIN].fillna(0)).cumprod()
    dd = curva / curva.cummax() - 1
    estres = dd < -0.10
    out = []
    for etiqueta, mask in [("Dias de estres (SPY en DD>10%)", estres),
                           ("Dias de calma", ~estres)]:
        re = ret_est.loc[INI:FIN][mask]; rs = RET_SPY.loc[INI:FIN][mask]
        out.append({"Regimen": etiqueta, "N dias": int(mask.sum()),
                    "Estrategia (medio diario)": f"{re.mean():+.3%}",
                    "SPY (medio diario)": f"{rs.mean():+.3%}"})
    return pd.DataFrame(out)


def analisis_whipsaw():
    """
    Que paso con el sector DESPUES de cada salida? Si tras vender el sector sube,
    fue whipsaw (el filtro saco de una buena). Si baja, el filtro protegio.
    Separa salidas por Donchian (piso) vs por ranking.
    """
    pesos, ev = construir_pesos_con_motivos(D["cierre"], D["high"], D["low"])
    cierre = D["cierre"]
    ev["Fecha"] = pd.to_datetime(ev["Fecha"])
    ev = ev[(ev["Fecha"] >= INI) & (ev["Accion"] == "SALE")]

    def fwd(fecha, activo, H):
        try:
            pos = IDX.get_loc(fecha)
        except KeyError:
            return np.nan
        if pos + H >= len(IDX):
            return np.nan
        p0, p1 = cierre[activo].iloc[pos], cierre[activo].iloc[pos + H]
        if pd.isna(p0) or pd.isna(p1) or p0 <= 0:
            return np.nan
        return p1 / p0 - 1

    filas = []
    for key, label in [("ruptura piso Donchian", "Salida por Donchian (piso)"),
                       ("cae del ranking", "Salida por ranking")]:
        sub = ev[ev["Motivo"].str.contains(key)]
        for H in [5, 10, 20, 40]:
            r = np.array([x for x in (fwd(f, a, H) for f, a in zip(sub["Fecha"], sub["Activo"])) if pd.notna(x)])
            filas.append({"Tipo de salida": label, "n": len(r), "Horizonte (ruedas)": H,
                          "Ret. medio del sector": f"{r.mean():+.2%}",
                          "% que subio despues": f"{(r > 0).mean()*100:.0f}%"})
    return pd.DataFrame(filas)


def main():
    cierre, high, low, ref_c = D["cierre"], D["high"], D["low"], D["ref_c"]

    # estrategia base (para referencia)
    pesos_base = md.construir_pesos(cierre, high, low)
    ret_base = md.retorno_cartera(pesos_base, RET_AP)
    s_base = md.stats_raw(ret_base.loc[INI:FIN])
    s_spy = md.stats_raw(RET_SPY.loc[INI:FIN])

    # ---- A) momentum absoluto clasico ----
    pesos_abs = pesos_abs_clasico(cierre, ref_c)
    ret_abs = md.retorno_cartera(pesos_abs, RET_AP)
    s_abs = md.stats_raw(ret_abs.loc[INI:FIN])
    expo_abs = pesos_abs[S].sum(axis=1).loc[INI:FIN].mean()
    expo_base = pesos_base[S].sum(axis=1).loc[INI:FIN].mean()

    print("="*96)
    print("  A) FILTRO ABSOLUTO: Donchian (base) vs Momentum absoluto clasico (Antonacci)")
    print(f"     ventana {INI.date()} -> {FIN.date()}")
    print("="*96)
    tabA = pd.DataFrame([
        _fila("SPY Buy & Hold", s_spy, 1.0),
        _fila("Base (filtro Donchian 20)", s_base, expo_base),
        _fila("Momentum absoluto clasico (ret 12m vs BIL)", s_abs, expo_abs),
    ]).set_index("Variante")
    print(tabA.to_string())
    print(f"\n  Operaciones: base={_nops(pesos_base)} | abs. clasico={_nops(pesos_abs)}")

    # ---- B) por regimen ----
    print("\n" + "="*96)
    print("  B) DESEMPEÑO POR REGIMEN DE MERCADO (estrategia base)")
    print("="*96)
    print("  Retorno en cada episodio bajista:")
    print(analisis_regimen(ret_base).to_string(index=False))
    print("\n  Captura en estres vs calma:")
    print(captura(ret_base).to_string(index=False))

    # ---- C) periodo minimo de tenencia ----
    print("\n" + "="*96)
    print("  C) PERIODO MINIMO DE TENENCIA")
    print("="*96)
    filasC = [_fila("Sin minimo (base)", s_base)]
    nopsC = {"Sin minimo (base)": _nops(pesos_base)}
    for dmin in [10, 20, 40]:
        p = pesos_con_min_hold(cierre, high, low, dmin)
        r = md.retorno_cartera(p, RET_AP)
        s = md.stats_raw(r.loc[INI:FIN])
        nombre = f"Minimo {dmin} ruedas"
        filasC.append(_fila(nombre, s)); nopsC[nombre] = _nops(p)
    tabC = pd.DataFrame(filasC).set_index("Variante")
    tabC["N oper."] = [nopsC[i] for i in tabC.index]
    print(tabC.to_string())

    # ---- D) whipsaw: que paso despues de cada salida ----
    print("\n" + "="*96)
    print("  D) ANALISIS DE WHIPSAW (retorno del sector tras cada salida)")
    print("="*96)
    tabD = analisis_whipsaw()
    print(tabD.to_string(index=False))

    # guardar Excel
    try:
        with pd.ExcelWriter("analisis_critico.xlsx", engine="openpyxl") as xw:
            tabA.to_excel(xw, sheet_name="A - Filtro absoluto")
            analisis_regimen(ret_base).to_excel(xw, sheet_name="B - Episodios", index=False)
            captura(ret_base).to_excel(xw, sheet_name="B - Captura", index=False)
            tabC.to_excel(xw, sheet_name="C - Minimo tenencia")
            tabD.to_excel(xw, sheet_name="D - Whipsaw", index=False)
        print("\n  Guardado: analisis_critico.xlsx")
    except Exception as e:
        print(f"\n  (No se pudo escribir Excel: {e})")


if __name__ == "__main__":
    main()
