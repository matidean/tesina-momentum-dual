# -*- coding: utf-8 -*-
"""
================================================================================
 ESTRATEGIA MOMENTUM DUAL - Rotacion sectorial S&P 500
 Tesina Finanzas Computacionales - UCEMA - Matias Dean
================================================================================

 Estrategia: Top 3 por fuerza relativa + filtro Donchian 20d
 comparada contra el Buy & Hold del SPY.

 Un solo archivo, DOS modos (se elige abajo en CONFIG -> MODO):

   MODO = "backtest"  -> corre la estrategia sobre ~10 años de historia
                         (usa un CSV local congelado = evita que cambien los datos para backtest)
                         y ademas guarda TODA la bitacora: métricas, cada
                         rotación, composición diaria y mensual, y resumen
                         por sector.

   MODO = "hoy"       -> baja datos nuevos y te dice, a fecha de hoy,
                         en que sectores hay que estar invertido y desde
                         cuándo mantenes esa composicion.

 Los dos modos usan EXACTAMENTE la misma logica de calculo de señales.
================================================================================
"""

import os
import numpy as np
import pandas as pd


# ==============================================================================
#  1) CONFIGURACION  (esto es lo unico que vas a tocar seguido)
# ==============================================================================

MODO = "backtest"          # "backtest"  o  "hoy"

SECTORES = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY",
            "XLP", "XLB", "XLU", "XLRE", "XLC"]     # 11 sectores SPDR
REFUGIO   = "BIL"          # bono corto del Tesoro (refugio). Alternativa: "SHV"
BENCHMARK = "SPY"          # para comparar (Buy & Hold)

VENTANA_MOM  = 252         # RELATIVO: retorno de los ultimos 252 dias (12 meses) - regla escrita
VENTANA_DON  = 20          # ABSOLUTO: canal de Donchian de 20 dias - regla escrita (entrada/salida)
N_SLOTS      = 3           # se invierte en el Top 3 (33,3% c/u)
RANK_ENTRADA = 3           # un sector NUEVO entra si esta en el Top 3
RANK_SALIDA  = 5           # una posicion se mantiene mientras no caiga debajo del puesto 5
MARGEN_RUPTURA = 0.003     # la ruptura del techo de Donchian debe ser de al menos +0,3%
COSTO        = 0.0020      # 0,20% de costo por operacion (sobre lo que rota)

# --- CADA CUANTO se rearma la cartera -----------------------------------------
#   "diario"  = revisa TODOS los dias 
#   "semanal" / "mensual" = se rearma en esa frecuecia.

FRECUENCIA_REBALANCEO = "diario"

FECHA_INICIO_DESCARGA = "2015-01-01"   # bajamos desde antes para "calentar" 252d
FECHA_FIN_DESCARGA    = None           # None = hasta hoy
ARCHIVO_CSV           = "datos_historicos.csv"   # la "foto" congelada



# --- VENTANA DE ANALISIS: que periodo queres MEDIR y graficar -----------------
# (los datos se bajan siempre completos; esto solo elige que tramo se reporta)
#
# Opcion A: los ultimos N meses. Poner un numero (ej 12 = ultimo año).
#           Si esto tiene un numero, se ignoran las dos fechas de abajo.
ULTIMOS_MESES = None                   # ej: 12  (o None para no usar esta opcion)
#
# Opcion B: fechas exactas de inicio y fin del analisis.
#           Dejar en None para analizar TODO el historial disponible.
FECHA_INICIO_ANALISIS = None           # ej: "2020-01-01"
FECHA_FIN_ANALISIS    = None           # ej: "2022-12-31"


# ==============================================================================
#  2) DESCARGA Y CARGA DE DATOS
# ==============================================================================

def _descargar(tickers, start, end):
    """Baja OHLC completo (Open, High, Low, Close), todo AJUSTADO, desde Yahoo."""
    import yfinance as yf
    data = yf.download(tickers, start=start, end=end,
                       auto_adjust=True, progress=False)
    piezas = []
    for campo, suf in [("Close", "close"), ("Open", "open"),
                       ("High", "high"), ("Low", "low")]:
        fr = data[campo].copy()
        if isinstance(fr, pd.Series):
            nom = tickers if isinstance(tickers, str) else tickers[0]
            fr = fr.to_frame(nom)
        fr.columns = [f"{c}_{suf}" for c in fr.columns]
        piezas.append(fr)
    return pd.concat(piezas, axis=1)


def cargar_datos_backtest():
    """
    Para el BACKTEST: si existe el CSV lo usa (foto congelada);
    si no existe, lo baja UNA vez y lo guarda.
    """
    todos = SECTORES + [REFUGIO, BENCHMARK]
    if os.path.exists(ARCHIVO_CSV):
        print(f"Leyendo la foto congelada: {ARCHIVO_CSV}")
        df = pd.read_csv(ARCHIVO_CSV, index_col=0, parse_dates=True)
    else:
        print("No hay CSV todavia. Bajando datos de Yahoo (una sola vez)...")
        df = _descargar(todos, FECHA_INICIO_DESCARGA, FECHA_FIN_DESCARGA)
        df.to_csv(ARCHIVO_CSV)
        print(f"Guardado en {ARCHIVO_CSV}. La proxima vez ya lo lee de ahi.")
    res = _separar(df)
    precios = res["cierre"]
    print(f"Rango de datos cargados: {precios.index[0].date()} -> "
          f"{precios.index[-1].date()}  ({len(precios)} filas)")
    if precios.index[0] > pd.Timestamp("2017-01-01"):
        print("  *** OJO: el historial parece corto (deberia arrancar ~2015-2016).")
        print("      Borra datos_historicos.csv y volve a correr para bajarlo completo.")
    return res


def descargar_datos_recientes(dias=400):
    """Para el MODO HOY: baja SOLO los ultimos ~dias (alcanza para 252 + 20)."""
    todos = SECTORES + [REFUGIO, BENCHMARK]
    inicio = (pd.Timestamp.today() - pd.Timedelta(days=int(dias * 1.6))).strftime("%Y-%m-%d")
    print(f"Bajando datos frescos desde {inicio} (para la senal de hoy)...")
    return _separar(_descargar(todos, inicio, None))


def _separar(df):
    """
    Ordena el DataFrame OHLC en un diccionario de piezas. Las SEÑALES usan el
    cierre (momentum) y el high/low (canal de Donchian); la EJECUCIÓN
    usa la apertura de t+1. Compatibilidad: si al CSV le faltan columnas, usa el
    cierre en su lugar y avisa para volver a bajar los datos completos.
    """
    def pick(suf):
        cols = [c for c in df.columns if str(c).endswith("_" + suf)]
        if not cols:
            return None
        sub = df[cols].copy()
        sub.columns = [str(c).replace("_" + suf, "") for c in cols]
        return sub.loc[:, ~sub.columns.duplicated()]

    cierre = pick("close")
    if cierre is None:   # CSV viejo con nombres pelados (sin sufijo): son cierres
        bare = df[[c for c in df.columns
                   if not str(c).endswith(("_open", "_high", "_low", "_volume"))]].copy()
        cierre = bare.loc[:, ~bare.columns.duplicated()]

    apertura, high, low = pick("open"), pick("high"), pick("low")
    faltan = [n for n, v in [("apertura", apertura), ("high", high), ("low", low)] if v is None]
    if faltan:
        print(f"  *** OJO: el CSV no tiene {', '.join(faltan)}. Se usa el cierre en su lugar.")
        print("      Borra datos_historicos.csv y volve a correr para bajar OHLC completo.")
    if apertura is None: apertura = cierre.copy()
    if high is None: high = cierre.copy()
    if low is None: low = cierre.copy()

    def sec(fr):
        return fr[[c for c in SECTORES if c in fr.columns]].ffill()

    return {
        "cierre": sec(cierre), "apertura": sec(apertura),
        "high": sec(high), "low": sec(low),
        "ref_c": cierre[REFUGIO].ffill(), "ref_o": apertura[REFUGIO].ffill(),
        "spy_c": cierre[BENCHMARK].ffill(), "spy_o": apertura[BENCHMARK].ffill(),
    }


# ==============================================================================
#  3) CALCULO DE SEÑALES
# ==============================================================================

def construir_pesos(cierre, high, low):
    """
    Matriz diaria de PESOS OBJETIVO. Columnas = sectores + REFUGIO.
    Reglas permanencia + margen, con canal de Donchian
    TRADICIONAL sobre maximos y minimos intradiarios:

      Upper_t = max(High de las 20 ruedas previas a t)
      Lower_t = min(Low  de las 20 ruedas previas a t)

    Para ENTRAR (un sector nuevo ocupa un lugar en la cartera):
      1) estar en el Top RANK_ENTRADA de fuerza relativa (252d), Y
      2) que su CIERRE supere el Upper por al menos MARGEN_RUPTURA (+0,3%).
      Si esta en el Top 3 pero no rompe, ese 33,3% queda en el REFUGIO.

    Una posicion comprada SE MANTIENE (banda de permanencia) hasta que:
      - su cierre cae por debajo del Lower (salida por tendencia), O
      - cae por debajo del puesto RANK_SALIDA (#5) en el ranking (rotacion).
    """
    momentum = cierre.pct_change(VENTANA_MOM, fill_method=None)
    don_sup = high.rolling(VENTANA_DON).max().shift(1)   # techo: max High 20 ruedas previas
    don_inf = low.rolling(VENTANA_DON).min().shift(1)    # piso:  min Low  20 ruedas previas
    ranking = momentum.rank(axis=1, ascending=False)     # 1 = el de mayor momentum

    columnas = list(cierre.columns) + [REFUGIO]
    pesos = pd.DataFrame(0.0, index=cierre.index, columns=columnas)
    w = 1.0 / N_SLOTS
    en_cartera = []   # sectores que hoy tenemos comprados (estado que se arrastra)

    for i, fecha in enumerate(cierre.index):
        m = momentum.iloc[i]
        rk = ranking.iloc[i]
        sup = don_sup.iloc[i]
        inf = don_inf.iloc[i]
        px = cierre.iloc[i]

        # --- 1) SALIDAS: sacar los que ya no califican (permanencia hasta puesto 5) ---
        siguen = []
        for s in en_cartera:
            if pd.isna(rk[s]):
                continue
            rompe_abajo = pd.notna(inf[s]) and px[s] < inf[s]
            fuera_ranking = rk[s] > RANK_SALIDA
            if not rompe_abajo and not fuera_ranking:
                siguen.append(s)
        en_cartera = siguen

        # --- 2) ENTRADAS: entrada al Top 3 que rompan el techo (+0,3%) ---
        if len(en_cartera) < N_SLOTS:
            candidatos = m.dropna().sort_values(ascending=False)
            for s in candidatos.index:
                if len(en_cartera) >= N_SLOTS:
                    break
                if s in en_cartera or rk[s] > RANK_ENTRADA:
                    continue
                rompe_arriba = pd.notna(sup[s]) and px[s] > sup[s] * (1 + MARGEN_RUPTURA)
                if rompe_arriba:
                    en_cartera.append(s)

        # --- 3) asignar pesos: cada sector 33,3%, lo que sobra al refugio ---
        for s in en_cartera:
            pesos.at[fecha, s] = w
        pesos.at[fecha, REFUGIO] = (N_SLOTS - len(en_cartera)) * w

    return pesos


def aplicar_frecuencia(pesos, frecuencia):
    """
    Esta función es la que controla cada cuánto la estrategia puede cambiar la cartera.
    Recibe los pesos "deseados" que salieron de construir_pesos (que se calculan todos los días) y, según la frecuencia que se elija, decide si esos cambios se aplican día a día o solo en fechas fijas.
    Convierte los pesos 'deseados' de cada dia en pesos que SOLO cambian en las
    fechas de rebalanceo (ultimo dia hábil de la semana o del mes). Entre
    rebalanceos la cartera se sostiene igual -> muchisima menos rotacion.
    Asi la estrategia 'se sube a la tendencia' y la deja correr.
    """
    if frecuencia == "diario":
        return pesos
    if frecuencia == "semanal":
        periodo = pesos.index.to_period("W")
    elif frecuencia == "mensual":
        periodo = pesos.index.to_period("M")
    else:
        raise ValueError("FRECUENCIA_REBALANCEO debe ser 'diario', 'semanal' o 'mensual'")

    # marcamos el ULTIMO dia habil de cada periodo como dia de rebalanceo
    es_reb = ~pd.Series(periodo, index=pesos.index).duplicated(keep="last")
    aplicado = pesos.copy()
    aplicado.loc[~es_reb.values] = np.nan     # los dias que no son rebalanceo se vacian
    aplicado = aplicado.ffill().fillna(0.0)   # se sostiene el ultimo rebalanceo
    return aplicado


# ==============================================================================
#  4) SIMULACION Y METRICAS
# ==============================================================================

def retorno_cartera(pesos, ret_apertura):
    """
    Retorno diario NETO con EJECUCION EN LA APERTURA DE t+1:
    la señal se decide con el cierre de t (fila 'pesos' en t), la orden se ejecuta
    en la apertura de t+1, y la posicion rinde de apertura(t+1) a apertura(t+2).
    Por eso los pesos van con shift(2) sobre los retornos apertura-a-apertura.
    El costo (0,20%) se cobra sobre la rotacion, en el momento de ejecutar.
    """
    ret = ret_apertura.reindex(columns=pesos.columns).fillna(0.0)
    w_efectivo = pesos.shift(2)                       # cierre t -> apertura t+1 -> rinde t+2
    bruto = (w_efectivo * ret).sum(axis=1)
    turnover = w_efectivo.diff().abs().sum(axis=1)
    return bruto - turnover * COSTO


def stats_raw(r):
    """Metricas numericas no dependen de librerias externas."""
    r = r.dropna()
    n = len(r)
    if n == 0:
        return {}
    total = (1 + r).prod() - 1
    cagr = (1 + r).prod() ** (252 / n) - 1
    vol = r.std() * np.sqrt(252)
    sharpe = (r.mean() * 252) / vol if vol > 0 else np.nan
    curva = (1 + r).cumprod()
    dd = curva / curva.cummax() - 1
    maxdd = dd.min()
    downside = r[r < 0].std() * np.sqrt(252)
    sortino = (r.mean() * 252) / downside if downside and downside > 0 else np.nan
    calmar = cagr / abs(maxdd) if maxdd < 0 else np.nan
    return {"total": total, "cagr": cagr, "vol": vol, "sharpe": sharpe,
            "sortino": sortino, "maxdd": maxdd, "calmar": calmar, "n": n}


def fila_formateada(nombre, s):
    return {"Estrategia": nombre,
            "Ret. total": f"{s['total']:6.1%}",
            "CAGR": f"{s['cagr']:6.1%}",
            "Volatilidad": f"{s['vol']:6.1%}",
            "Sharpe": f"{s['sharpe']:5.2f}",
            "Sortino": f"{s['sortino']:5.2f}",
            "Max Drawdown": f"{s['maxdd']:6.1%}",
            "Calmar": f"{s['calmar']:5.2f}"}


# ==============================================================================
#  5) BITACORA: rotaciones, trades y composicion
# ==============================================================================

def _comp_dict(fila):
    """De una fila de pesos a un dict {activo: peso} con solo lo que tiene peso."""
    return {a: float(w) for a, w in fila.items() if w > 1e-6}


def _comp_texto(comp):
    """Formatea una composicion como 'XLK 33% | XLF 33% | BIL 33%'."""
    return " | ".join(f"{a} {w:.0%}"
                      for a, w in sorted(comp.items(), key=lambda x: (-x[1], x[0])))


def bitacora_rotaciones(pesos):
    """
    Detecta cada dia en que la cartera cambia de composición y arma una tabla:
    fecha, cuántos días duro la composicion anterior, que salió, que entró,
    y cómo quedó la cartera. Devuelve (tabla, resumen).
    """
    p = pesos.round(4)
    cambio = (p.diff().abs().sum(axis=1) > 1e-6)
    cambio.iloc[0] = True
    pos = np.where(cambio.values)[0]

    filas = []
    prev = set()
    compras = ventas = 0

    for k, i in enumerate(pos):
        fecha = p.index[i]
        comp = _comp_dict(p.iloc[i])
        actual = set(comp.keys())

        entran = actual - prev
        salen = prev - actual
        compras += len(entran)
        ventas += len(salen)

        fin = pos[k + 1] if k + 1 < len(pos) else len(p)
        duracion = int(fin - i)

        def solo_sectores(conjunto):
            return sorted(a for a in conjunto if a != REFUGIO)

        detalle = []
        s_out = solo_sectores(salen)
        s_in = solo_sectores(entran)
        if s_out:
            detalle.append("salen: " + ", ".join(s_out))
        if s_in:
            detalle.append("entran: " + ", ".join(s_in))
        if REFUGIO in entran and REFUGIO not in prev:
            detalle.append("-> a refugio")
        if REFUGIO in salen:
            detalle.append("<- sale de refugio")
        bil_prev = float(pesos.iloc[pos[k - 1]][REFUGIO]) if k > 0 else 0.0
        bil_now = comp.get(REFUGIO, 0.0)
        if k > 0 and abs(bil_now - bil_prev) > 1e-6 and REFUGIO in actual and REFUGIO in prev:
            detalle.append(f"{REFUGIO} {bil_prev:.0%}->{bil_now:.0%}")

        filas.append({
            "Fecha": fecha.date(),
            "Dias que dura": duracion,
            "Composicion": _comp_texto(comp),
            "Cambio": " ; ".join(detalle) if detalle else ("apertura inicial" if k == 0 else "ajuste"),
        })
        prev = actual

    tabla = pd.DataFrame(filas)

    peso_equity = 1.0 - pesos[REFUGIO]
    pct_en_equity = peso_equity.mean()
    pct_full_refugio = (pesos[REFUGIO] > 0.99).mean()
    dur_prom = tabla["Dias que dura"].mean() if len(tabla) else 0

    resumen = {
        "Dias con cambio de cartera (rebalanceos)": len(tabla),
        "Posiciones abiertas (compras)": compras,
        "Posiciones cerradas (ventas)": ventas,
        "Duracion promedio de una composicion (dias habiles)": round(float(dur_prom), 1),
        "% del tiempo invertido en acciones": f"{pct_en_equity:.1%}",
        "% del tiempo 100% en refugio (BIL)": f"{pct_full_refugio:.1%}",
    }
    return tabla, resumen


def composicion_mensual(pesos):
    """Foto de la cartera al ULTIMO dia habil de cada mes."""
    mensual = pesos.resample("ME").last()
    mensual = mensual[(mensual.abs().sum(axis=1) > 0)]
    texto = mensual.apply(lambda fila: _comp_texto(_comp_dict(fila)), axis=1)
    salida = (mensual * 100).round(0)
    salida.index = salida.index.date
    salida["Composicion"] = texto.values
    return salida


def resumen_por_sector(pesos):
    """Por cada activo: cuantos dias estuvo en cartera y cuantas veces entro."""
    filas = []
    for s in SECTORES + [REFUGIO]:
        if s not in pesos.columns:
            continue
        invertido = pesos[s] > 1e-6
        dias = int(invertido.sum())
        entradas = int(((~invertido.shift(1, fill_value=False)) & invertido).sum())
        filas.append({"Activo": s, "Dias en cartera": dias,
                      "% del tiempo": f"{dias/len(pesos):.1%}",
                      "Veces que entro": entradas})
    return pd.DataFrame(filas).sort_values("Dias en cartera", ascending=False)


# ==============================================================================
#  6) MODO BACKTEST
# ==============================================================================

def estadisticas_por_activo(datos, ini, fin):
    """
    Para cada ETF (sectores + refugio + benchmark): como le fue de PUNTA A PUNTA
    si lo hubieras comprado y mantenido en la ventana [ini, fin]. Sirve para
    verificar los datos y para contexto.
    """
    cierres = datos["cierre"].copy()
    cierres[REFUGIO] = datos["ref_c"]
    cierres[BENCHMARK] = datos["spy_c"]
    cierres = cierres.loc[ini:fin]

    filas = []
    for col in cierres.columns:
        serie = cierres[col].dropna()
        if len(serie) < 2:
            continue
        n = len(serie)
        ret_total = serie.iloc[-1] / serie.iloc[0] - 1
        cagr = (serie.iloc[-1] / serie.iloc[0]) ** (252 / n) - 1
        r = serie.pct_change().dropna()
        vol = r.std() * np.sqrt(252)
        curva = serie / serie.iloc[0]
        max_dd = (curva / curva.cummax() - 1).min()
        filas.append({
            "Activo": col,
            "Precio ini": round(float(serie.iloc[0]), 2),
            "Precio fin": round(float(serie.iloc[-1]), 2),
            "Ret. total (punta a punta)": f"{ret_total:.1%}",
            "CAGR": f"{cagr:.1%}",
            "Vol anual": f"{vol:.1%}",
            "Max Drawdown": f"{max_dd:.1%}",
            "Mejor dia": f"{r.max():.1%}",
            "Peor dia": f"{r.min():.1%}",
        })
    return pd.DataFrame(filas).sort_values("Activo").reset_index(drop=True)


def correr_backtest():
    datos = cargar_datos_backtest()

    # retornos APERTURA-a-apertura (para ejecutar en t+1); refugio incluido
    ret_apertura = datos["apertura"].pct_change(fill_method=None)
    ret_apertura[REFUGIO] = datos["ref_o"].pct_change(fill_method=None)
    ret_spy = datos["spy_c"].pct_change(fill_method=None)   # benchmark buy&hold (cierre)

    pesos = construir_pesos(datos["cierre"], datos["high"], datos["low"])  # SENALES
    pesos = aplicar_frecuencia(pesos, FRECUENCIA_REBALANCEO)
    ret_est = retorno_cartera(pesos, ret_apertura)          # EJECUCION apertura t+1

    # --- elegir la ventana de analisis (que tramo se mide y grafica) ---
    warmup = pesos.index[VENTANA_MOM + VENTANA_DON]   # primer dia con senales validas
    fin = pd.Timestamp(FECHA_FIN_ANALISIS) if FECHA_FIN_ANALISIS else pesos.index[-1]

    if ULTIMOS_MESES:
        ini = pd.Timestamp(fin) - pd.DateOffset(months=int(ULTIMOS_MESES))
    elif FECHA_INICIO_ANALISIS:
        ini = pd.Timestamp(FECHA_INICIO_ANALISIS)
    else:
        ini = warmup

    # no dejar arrancar antes de que existan senales validas (el warmup de 252d)
    if ini < warmup:
        print(f"  (aviso: adelanto el inicio a {warmup.date()} porque antes "
              f"no hay senales validas)")
        ini = warmup

    ret_spy_v = ret_spy.loc[ini:fin]
    ret_est_v = ret_est.loc[ini:fin]
    pesos_v = pesos.loc[ini:fin]

    s_spy = stats_raw(ret_spy_v)
    s_est = stats_raw(ret_est_v)

    print("\n" + "=" * 78)
    print("  RESULTADOS DEL BACKTEST")
    print(f"  Periodo: {ret_est_v.index[0].date()}  ->  {ret_est_v.index[-1].date()}")
    print(f"  Rebalanceo: {FRECUENCIA_REBALANCEO}  |  Ejecucion: apertura t+1  |  "
          f"Donchian: {VENTANA_DON}d (+{MARGEN_RUPTURA:.1%})  |  "
          f"Momentum: {VENTANA_MOM}d  |  Permanencia: Top {RANK_SALIDA}  |  Costo: {COSTO:.2%}")
    print("=" * 78)
    tabla = pd.DataFrame([
        fila_formateada("Benchmark (SPY)", s_spy),
        fila_formateada("Momentum Dual", s_est),
    ]).set_index("Estrategia")
    print(tabla.to_string())

    reduccion = abs(s_spy["maxdd"]) - abs(s_est["maxdd"])
    print("\n  Reduccion de drawdown vs SPY: "
          f"{s_est['maxdd']:.1%} contra {s_spy['maxdd']:.1%}  "
          f"(mejora de {reduccion*100:.1f} puntos)")
    print("=" * 78)

    tabla_rot, resumen = bitacora_rotaciones(pesos_v)
    print("\n  BITACORA DE OPERACIONES")
    print("  " + "-" * 74)
    for k, v in resumen.items():
        print(f"  {k}: {v}")
    print("  " + "-" * 74)
    print("  Ultimas 12 rotaciones:")
    print(tabla_rot.tail(12).to_string(index=False))

    mensual = composicion_mensual(pesos_v)
    print("\n  COMPOSICION AL CIERRE DE CADA MES (ultimos 12):")
    print(mensual[["Composicion"]].tail(12).to_string())

    por_sector = resumen_por_sector(pesos_v)
    print("\n  CUANTO TIEMPO ESTUVO EN CADA ACTIVO:")
    print(por_sector.to_string(index=False))

    # --- estadisticas por activo (punta a punta) + verificacion de datos ---
    est_activo = estadisticas_por_activo(datos, ini, fin)
    print("\n  COMO LE FUE A CADA ETF DE PUNTA A PUNTA (buy & hold, en la ventana):")
    print(est_activo.to_string(index=False))

    tabla_rot.to_csv("bitacora_rotaciones.csv", index=False)
    mensual.to_csv("composicion_mensual.csv")
    por_sector.to_csv("resumen_por_sector.csv", index=False)
    (pesos_v * 100).round(1).to_csv("composicion_diaria.csv")
    est_activo.to_csv("estadisticas_por_activo.csv", index=False)

    # matematica cruda para comprobar datos: variacion diaria y correlaciones
    cierres_full = datos["cierre"].copy()
    cierres_full[REFUGIO] = datos["ref_c"]
    cierres_full[BENCHMARK] = datos["spy_c"]
    variacion = cierres_full.loc[ini:fin].pct_change(fill_method=None)
    (variacion * 100).round(3).to_csv("variacion_diaria.csv")
    variacion[SECTORES].corr().round(3).to_csv("correlacion_sectores.csv")

    print("\n  Tablas guardadas: bitacora_rotaciones.csv | composicion_mensual.csv |")
    print("                    resumen_por_sector.csv | composicion_diaria.csv |")
    print("                    estadisticas_por_activo.csv | variacion_diaria.csv |")
    print("                    correlacion_sectores.csv")

    _graficar(ret_spy_v, ret_est_v)
    _reporte_quantstats_opcional(ret_est_v)


def _graficar(ret_spy, ret_est):
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True,
                                   gridspec_kw={"height_ratios": [2, 1]})
    for r, etq in [(ret_spy, "Benchmark SPY"), (ret_est, "Momentum Dual")]:
        curva = (1 + r).cumprod()
        ax1.plot(curva.index, curva.values, label=etq)
    ax1.set_title("Crecimiento de $1 invertido")
    ax1.set_yscale("log")
    ax1.legend(); ax1.grid(True, alpha=0.3)

    for r, etq in [(ret_spy, "Benchmark SPY"), (ret_est, "Momentum Dual")]:
        curva = (1 + r).cumprod()
        dd = curva / curva.cummax() - 1
        ax2.plot(dd.index, dd.values, label=etq)
    ax2.set_title("Drawdown (caida desde el maximo)")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig("resultado_backtest.png", dpi=110)
    print("\n  Grafico guardado en: resultado_backtest.png")
    try:
        plt.show()
    except Exception:
        pass


def _reporte_quantstats_opcional(retornos):
    try:
        try:
            import quantstats_lumi as qs
        except ImportError:
            import quantstats as qs
        qs.reports.html(retornos, output="reporte_quantstats.html",
                        title="Momentum Dual")
        print("  Reporte QuantStats guardado en: reporte_quantstats.html")
    except Exception as e:
        print(f"  (QuantStats no disponible, se omite el reporte extra: {e})")


# ==============================================================================
#  7) MODO HOY  -> señal en tiempo real
# ==============================================================================

def senal_de_hoy():
    datos = descargar_datos_recientes()
    precios = datos["cierre"]
    pesos = construir_pesos(datos["cierre"], datos["high"], datos["low"])
    pesos = aplicar_frecuencia(pesos, FRECUENCIA_REBALANCEO)

    fecha = pesos.index[-1]
    fila = _comp_dict(pesos.iloc[-1])
    momentum = precios.pct_change(VENTANA_MOM, fill_method=None).iloc[-1]
    top = momentum.dropna().sort_values(ascending=False).head(N_SLOTS)

    tabla_rot, _ = bitacora_rotaciones(pesos)
    ult = tabla_rot.iloc[-1]

    print("\n" + "=" * 62)
    print("  SENAL DE HOY - Momentum Dual")
    print(f"  Datos al cierre del: {fecha.date()}")
    print("=" * 62)
    print("  Top 3 sectores por fuerza relativa (12m):")
    for s, val in top.items():
        estado = "COMPRAR" if s in fila else "-> a refugio"
        print(f"     {s:5s}  momentum {val:6.1%}   {estado}")
    print("  ---------------------------------------------")
    print("  ASIGNACION SUGERIDA HOY:")
    for activo, peso in sorted(fila.items(), key=lambda x: (-x[1], x[0])):
        etiqueta = "REFUGIO (bono corto)" if activo == REFUGIO else "sector"
        print(f"     {activo:5s}  {peso:5.1%}   {etiqueta}")
    print("  ---------------------------------------------")
    print(f"  Manteniendo esta composicion desde: {ult['Fecha']} "
          f"({ult['Dias que dura']} dias habiles)")
    print("=" * 62)


# ==============================================================================
#  8) PUNTO DE ENTRADA
# ==============================================================================

if __name__ == "__main__":
    if MODO == "backtest":
        correr_backtest()
    elif MODO == "hoy":
        senal_de_hoy()
    else:
        print("MODO invalido. Elegi 'backtest' o 'hoy' arriba en CONFIG.")
