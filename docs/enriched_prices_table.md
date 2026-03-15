# Tabla: `enriched_prices_table`

**Ubicación:** `yfinance-gcp.yfinance_raw.enriched_prices_table`
**Fuente:** Generada desde `daily_prices` (precios históricos) y `companies` (datos fundamentales)

---

## Descripción general

Esta tabla combina precios diarios con indicadores técnicos calculados y datos fundamentales de cada empresa. Su propósito es centralizar toda la información necesaria para análisis cuantitativo y modelos de IA.

---

## Columnas

### Datos base

| Columna   | Tipo    | Descripción                                      |
|-----------|---------|--------------------------------------------------|
| `date`    | DATE    | Fecha de la sesión bursátil                      |
| `symbol`  | STRING  | Ticker de la acción (ej. AAPL, MSFT)             |
| `close`   | FLOAT   | Precio de cierre del día                         |
| `volume`  | INTEGER | Volumen de acciones negociadas                   |

---

### Datos fundamentales (de la tabla `companies`)

| Columna               | Tipo    | Descripción                                                  |
|-----------------------|---------|--------------------------------------------------------------|
| `sector`              | STRING  | Sector económico de la empresa (ej. Technology)              |
| `industry`            | STRING  | Industria específica (ej. Consumer Electronics)              |
| `market_cap`          | FLOAT   | Capitalización de mercado en dólares                         |
| `shares_outstanding`  | FLOAT   | Número de acciones en circulación                            |
| `trailing_eps`        | FLOAT   | Beneficio por acción (EPS) de los últimos 12 meses           |
| `beta`                | FLOAT   | Volatilidad relativa al mercado (β > 1 = más volátil)        |
| `recommendation_key`  | STRING  | Recomendación de analistas: `buy`, `hold`, `sell`, etc.      |

---

### Indicadores técnicos

#### PER (Price-to-Earnings Ratio)

| Columna     | Fórmula                          | Descripción                                    |
|-------------|----------------------------------|------------------------------------------------|
| `pe_ratio`  | `close / trailing_eps`           | Veces que el mercado paga por cada $ de ganancia. NULL si EPS = 0 |

---

#### RSI (Relative Strength Index)

| Columna   | Ventana | Descripción                                                                 |
|-----------|---------|-----------------------------------------------------------------------------|
| `rsi_14`  | 14 días | Índice de fuerza relativa. Rango 0–100. >70 = sobrecomprado, <30 = sobrevendido |

**Cálculo:**
1. Se separan cambios diarios en ganancias (`gain`) y pérdidas (`loss`)
2. Se promedian sobre 14 períodos
3. RSI = `100 - (100 / (1 + avg_gain / avg_loss))`

---

#### Medias Móviles Simples (SMA)

Calculadas internamente; se exponen derivados:

| Columna        | Ventana   | Uso                                         |
|----------------|-----------|---------------------------------------------|
| `macd_line`    | SMA12 - SMA26 | Proxy de MACD. Positivo = momentum alcista |
| `long_term_trend` | SMA50 vs SMA200 | `'Bullish'` si SMA50 > SMA200, `'Bearish'` si no |
| `dist_sma_200` | 200 días  | Distancia % del precio respecto a SMA200    |

---

#### Bandas de Bollinger

Basadas en SMA26 y desviación estándar de 20 períodos:

| Columna          | Fórmula                         | Descripción                                              |
|------------------|---------------------------------|----------------------------------------------------------|
| `bollinger_high` | `SMA26 + 2 * stddev_20`         | Banda superior                                           |
| `bollinger_low`  | `SMA26 - 2 * stddev_20`         | Banda inferior                                           |
| `bollinger_pct`  | `(close - band_low) / (4 * stddev_20)` | Posición del precio dentro de las bandas. 0 = mínimo, 1 = máximo |

---

#### Distancia a máximos/mínimos anuales (52 semanas)

| Columna              | Descripción                                                        |
|----------------------|--------------------------------------------------------------------|
| `pct_from_52w_high`  | % de caída respecto al máximo de 52 semanas. Negativo = bajó del máx |
| `pct_from_52w_low`   | % de subida respecto al mínimo de 52 semanas. Positivo = subió del mín |

---

#### Momentum

| Columna         | Ventana  | Descripción                                                |
|-----------------|----------|------------------------------------------------------------|
| `momentum_10d`  | 10 días  | Retorno % de los últimos 10 días hábiles                   |

---

## Esquema del pipeline

```
daily_prices  ──────────────────────────────┐
  └─ base_stats  (SMAs, stddev, 52w, change)│
       └─ rsi_prep (gain / loss split)      │
            └─ rsi_final (avg_gain/loss)    │
                  │                         │
                  └────────── JOIN ─────────┘
                         companies
                              │
                              ▼
                  enriched_prices_table
```

---

## Notas de uso

- Los primeros registros de cada símbolo pueden tener indicadores incompletos (ventanas de cálculo no saturadas).
- `pe_ratio`, `bollinger_pct` y distancias devuelven `NULL` cuando el denominador es 0 o nulo, en lugar de errores.
- `recommendation_key` proviene de analistas externos y puede estar desactualizado respecto a la fecha de la fila.
- La tabla se recrea completa con `CREATE OR REPLACE TABLE` en cada ejecución.
