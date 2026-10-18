# Estrategia de Momentum Dual sectorial sobre el S&P 500

Código de la tesina de **Finanzas Computacionales (UCEMA)** — Dean, Matías.

Implementa y evalúa una estrategia cuantitativa de **Momentum Dual** sobre los 11 sectores
del S&P 500 (ETFs SPDR), que combina momentum relativo (Top 3 por fuerza relativa de 252 días)
con un filtro de momentum absoluto (canal de Donchian de 20 días) y un refugio táctico en un ETF
de bonos del Tesoro de corto plazo (BIL). El backtest cubre el período 2016-2026 con datos diarios
y un costo de transacción del 0,20% por operación.

---

## Requisitos

- Python 3.12
- Las librerías del archivo `requirements.txt`.

Instalación (recomendado, dentro de un entorno virtual):

```bash
pip install -r requirements.txt
```

---

## Estructura de archivos

| Archivo | Qué hace |
|---|---|
| `momentum_dual.py` | **Motor** de la estrategia: señales, backtest, bitácora de rotaciones y gráfico principal. Autónomo. |
| `robustez_exposicion.py` | Comparador de exposición (estrategia vs. carteras de referencia de igual exposición) y registro de motivos de cada señal. |
| `analisis_critico.py` | Filtro absoluto clásico de Antonacci, desempeño por régimen de mercado, captura, período mínimo de tenencia y análisis de *whipsaw*. |
| `analisis_sensibilidad.py` | Grilla de sensibilidad: varía un parámetro por vez (Donchian, momentum, frecuencia, margen, permanencia, costo). |
| `medicion_liquidez.py` | Mide la liquidez del universo (volumen diario promedio operado en dólares). |
| `datos_historicos.csv` | **Foto congelada** de los datos de Yahoo Finance (entrada del backtest). No borrar. |

---

## Cómo correr

Los scripts comparten `momentum_dual.py` y `datos_historicos.csv`, así que mantené todos los
archivos en la **misma carpeta**.

**Importante — orden de ejecución.** Cada script se apoya en el anterior:

```
momentum_dual.py  →  robustez_exposicion.py  →  analisis_critico.py
```

`analisis_critico.py` importa una función de `robustez_exposicion.py`, que a su vez usa
`momentum_dual.py`. Por eso, para reproducir TODO el análisis, corré en este orden:

```bash
python momentum_dual.py          # 1) estrategia + backtest + bitácora + gráfico
python robustez_exposicion.py    # 2) comparador de exposición + motivos
python analisis_critico.py       # 3) análisis crítico (régimen, whipsaw, etc.)
python analisis_sensibilidad.py  # 4) grilla de sensibilidad
python medicion_liquidez.py      # 5) liquidez del universo
```

Si solo querés **ver funcionar la estrategia**, con el paso 1 (`momentum_dual.py`) alcanza: es
autónomo. Los pasos 2 a 5 son los análisis de robustez que acompañan la tesina.

### Dos modos en `momentum_dual.py`

En la sección CONFIG (arriba del archivo) está la variable `MODO`:

- `MODO = "backtest"` → corre la estrategia sobre los ~10 años de historia (usa la foto congelada).
- `MODO = "hoy"` → baja datos frescos y dice en qué sectores habría que estar invertido hoy.

---

## Reproducibilidad

El archivo `datos_historicos.csv` es la **foto congelada** de los precios: garantiza que cualquiera
que corra el código obtenga exactamente los mismos resultados que figuran en la tesina. Como Yahoo
Finance reajusta su historia con el tiempo, **no conviene borrarlo**. Si se elimina, `momentum_dual.py`
vuelve a descargar los datos de Yahoo (requiere conexión) y los resultados pueden variar levemente.

`medicion_liquidez.py` sí descarga datos de volumen de Yahoo Finance en el momento (requiere conexión),
porque la liquidez se mide sobre el último año disponible.

---

## Qué genera cada script

- `momentum_dual.py`: `resultado_backtest.png`, `reporte_quantstats.html`, y varias bitácoras en CSV
  (rotaciones, composición diaria y mensual, resumen por sector, etc.).
- `robustez_exposicion.py`: `comparador_exposicion.csv`, `motivos_senales.csv`, `robustez_exposicion.xlsx`.
- `analisis_critico.py`: `analisis_critico.xlsx` (filtro absoluto, episodios, captura, mínimo de tenencia, whipsaw).
- `analisis_sensibilidad.py`: `analisis_sensibilidad.xlsx` (una hoja por parámetro).
- `medicion_liquidez.py`: `liquidez_etfs.csv` y `liquidez_etfs_legible.csv`.

Estas salidas están en `.gitignore` porque se reproducen corriendo el código.
