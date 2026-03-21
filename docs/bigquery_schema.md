# BigQuery Dataset: `yfinance-gcp.yfinance_raw`

Pipeline de datos financieros con Yahoo Finance como fuente. Datos de empresas del S&P500, STOXX600 y otros índices.

---

## Tablas base

### `companies` — Metadata de empresas
Actualización semanal. Una fila por semana por símbolo (acumula historial).

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `symbol` | STRING | Ticker (ej. AAPL, BBVA.MC) |
| `short_name` | STRING | Nombre corto |
| `sector` | STRING | Sector (Technology, Financials…) |
| `industry` | STRING | Industria específica |
| `country` | STRING | País |
| `market_cap` | FLOAT | Capitalización de mercado en $ |
| `beta` | FLOAT | Volatilidad relativa al mercado |
| `trailing_eps` | FLOAT | Beneficio por acción últimos 12m |
| `forward_eps` | FLOAT | Beneficio por acción estimado |
| `dividend_yield` | FLOAT | Rentabilidad por dividendo |
| `return_on_equity` | FLOAT | ROE |
| `recommendation_key` | STRING | Consenso analistas: `strong_buy`, `buy`, `hold`, `underperform`, `sell` |
| `target_mean_price` | FLOAT | Precio objetivo medio de analistas |
| `is_active` | BOOL | Si el símbolo está activo en Yahoo Finance |
| `updated_at` | DATE | Fecha del snapshot |

**Ejemplo:**
```
symbol: AAPL | sector: Technology | market_cap: 3.2T | beta: 1.2 | recommendation_key: buy | updated_at: 2026-03-16
```

---

### `daily_prices` — Precios OHLCV diarios
3.3M filas. Fuente cruda de precios. MERGE por (date, symbol), nunca duplica.

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `date` | DATE | Fecha de sesión |
| `symbol` | STRING | Ticker |
| `open` | FLOAT | Precio apertura |
| `high` | FLOAT | Máximo del día |
| `low` | FLOAT | Mínimo del día |
| `close` | FLOAT | Precio cierre |
| `adj_close` | FLOAT | Cierre ajustado por splits/dividendos |
| `volume` | INTEGER | Volumen negociado |

**Ejemplo:**
```
date: 2026-03-18 | symbol: AAPL | open: 214.5 | high: 217.3 | low: 213.1 | close: 216.8 | volume: 52M
```

---

## Tabla enriquecida

### `enriched_prices_table` — Precios + indicadores técnicos + fundamentales
13M filas. Generada diariamente por `daily_enrich`. Es la tabla central para análisis.

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `date` | DATE | Fecha |
| `symbol` | STRING | Ticker |
| `close` | FLOAT | Precio cierre |
| `volume` | INTEGER | Volumen |
| `sector` | STRING | Sector (de companies) |
| `industry` | STRING | Industria (de companies) |
| `market_cap` | FLOAT | Market cap en $ |
| `trailing_eps` | FLOAT | EPS últimos 12m |
| `pe_ratio` | FLOAT | PER (close / trailing_eps) |
| `beta` | FLOAT | Volatilidad relativa |
| `recommendation_key` | STRING | Recomendación analistas |
| `rsi_14` | FLOAT | RSI 14 períodos (0-100). >70 sobrecomprado, <30 sobrevendido |
| `long_term_trend` | STRING | `Bullish` si SMA50 > SMA200, `Bearish` si no |
| `dist_sma_200` | FLOAT | Distancia % del precio a la SMA200 (0.10 = 10% por encima) |
| `macd_line` | FLOAT | MACD proxy (SMA12 - SMA26). Positivo = momentum alcista |
| `momentum_10d` | FLOAT | Retorno % últimos 10 días hábiles |
| `bollinger_pct` | FLOAT | Posición en Bollinger (0=banda baja, 1=banda alta) |
| `bollinger_high` | FLOAT | Banda superior de Bollinger |
| `bollinger_low` | FLOAT | Banda inferior de Bollinger |
| `pct_from_52w_high` | FLOAT | % de caída respecto al máximo de 52 semanas (negativo) |
| `pct_from_52w_low` | FLOAT | % de subida respecto al mínimo de 52 semanas |

**Ejemplo:**
```
date: 2026-03-18 | symbol: MSFT | close: 389.2 | rsi_14: 58.3 | long_term_trend: Bullish
dist_sma_200: 0.12 | momentum_10d: 0.045 | bollinger_pct: 0.62 | recommendation_key: buy
```

---

## Outputs del scanner

### `war_dip_results` — Scanner de correcciones macro
Snapshot diario. Detecta acciones con uptrend consolidado (Bullish en 3m, 6m y 1y) que han caído entre 2%-40% en 5 días por factores macro. Market cap >= $2B. Top 50 por score. Se acumula día a día.

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `run_date` | DATE | Fecha de ejecución del scanner |
| `symbol` | STRING | Ticker |
| `sector` / `industry` | STRING | Sector e industria |
| `close` | FLOAT | Precio cierre |
| `market_cap_bn` | FLOAT | Market cap en miles de millones $ |
| `chg_1d_pct` | FLOAT | Caída en 1 día (%) |
| `chg_3d_pct` | FLOAT | Caída en 3 días (%) |
| `chg_5d_pct` | FLOAT | Caída en 5 días (%) — el dip principal |
| `chg_7d_pct` | FLOAT | Caída en 7 días (%) |
| `perf_1y_total_pct` | FLOAT | Rendimiento 1 año antes del dip (%) |
| `perf_6m_total_pct` | FLOAT | Rendimiento 6 meses antes del dip (%) |
| `rsi_14` | FLOAT | RSI actual |
| `dist_sma200_pct` | FLOAT | Distancia a SMA200 en % |
| `pct_from_52w_high` | FLOAT | % caída desde máximo 52 semanas |
| `trend_now/3m/6m/1y` | STRING | Tendencia en distintos horizontes |
| `recommendation_key` | STRING | Recomendación analistas |
| `score_a1_trend_1y` | FLOAT | Score componente: fuerza uptrend 1y (0-15) |
| `score_a2_trend_6m` | FLOAT | Score componente: fuerza uptrend 6m (0-15) |
| `score_b1_dip_size` | FLOAT | Score componente: magnitud del dip (0-15) |
| `score_b2_dip_gradual` | FLOAT | Score componente: gradualidad caída (0-10) |
| `score_c1_rsi` | FLOAT | Score componente: RSI sobrevendido (0-12) |
| `score_c2_bollinger` | FLOAT | Score componente: posición Bollinger (0-8) |
| `score_d_sma200` | FLOAT | Score componente: salud estructural (0-15) |
| `score_e_analyst` | FLOAT | Score componente: consenso analistas (0-10) |
| `score_total` | FLOAT | Score total 0-100 |

**Ejemplo:**
```
run_date: 2026-03-20 | symbol: BBVA.MC | sector: Financial Services
close: 17.92 | market_cap_bn: 108.3 | chg_5d_pct: -2.18
perf_1y_total_pct: 40.02 | rsi_14: 48.14 | score_total: 32.5
recommendation_key: buy
```

---

## Vistas (calculadas automáticamente)

### `bullish_screener` — Acciones en tendencia alcista fuerte
Vista diaria. Filtra acciones con: `long_term_trend = Bullish`, RSI entre 45-68, momentum positivo, market cap >= $2B, recomendación `buy` o `strong_buy`. Score 0-100. Top 50.

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `screen_date` | DATE | Fecha del screening |
| `symbol` | STRING | Ticker |
| `sector` / `industry` | STRING | Sector e industria |
| `close` | FLOAT | Precio |
| `market_cap_bn` | FLOAT | Market cap en miles de millones $ |
| `rsi_14` | FLOAT | RSI (45-68 en esta vista) |
| `momentum_10d_pct` | FLOAT | Momentum 10 días en % |
| `dist_sma200_pct` | FLOAT | % por encima de SMA200 |
| `pct_from_52w_high` | FLOAT | % desde máximo 52 semanas |
| `recommendation_key` | STRING | `buy` o `strong_buy` |
| `score_momentum` | FLOAT | Componente momentum (0-25) |
| `score_rsi` | FLOAT | Componente RSI sweet spot (0-25) |
| `score_sma200` | FLOAT | Componente posición SMA200 (0-20) |
| `score_analyst` | FLOAT | Componente analistas (0-15) |
| `score_52w` | FLOAT | Componente cercanía a máximos (0-15) |
| `score_total` | FLOAT | Score total 0-100 |

**Ejemplo:**
```
screen_date: 2026-03-21 | symbol: DPLM.L | sector: Industrials
close: 5725 | rsi_14: 59.65 | momentum_10d_pct: 10.2
dist_sma200_pct: 7.26 | recommendation_key: buy | score_total: 79.6
```

---

### `daily_watchlist` — Lista unificada del día
Vista que combina `bullish_screener` (tipo=ALCISTA) y `war_dip_results` (tipo=DIP) en una sola tabla. ~100 acciones diarias ordenadas por score. **Esta es la vista principal para Power BI.**

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `date` | DATE | Fecha |
| `tipo` | STRING | `ALCISTA` o `DIP` |
| `symbol` | STRING | Ticker |
| `sector` / `industry` | STRING | Sector e industria |
| `close` | FLOAT | Precio |
| `market_cap_bn` | FLOAT | Market cap en miles de millones $ |
| `rsi_14` | FLOAT | RSI |
| `momentum_10d_pct` | FLOAT | Momentum 10 días en % |
| `dist_sma200_pct` | FLOAT | % respecto a SMA200 |
| `pct_from_52w_high` | FLOAT | % desde máximo 52 semanas |
| `recommendation_key` | STRING | Recomendación analistas |
| `score` | FLOAT | Score total 0-100 |
| `dip_5d_pct` | FLOAT | Caída en 5 días en % (solo para tipo=DIP, NULL para ALCISTA) |

**Ejemplo:**
```
date: 2026-03-21 | tipo: ALCISTA | symbol: BTU | sector: Energy
close: 37.31 | rsi_14: 56.2 | momentum_10d_pct: 14.59
recommendation_key: strong_buy | score: 77.9 | dip_5d_pct: NULL

date: 2026-03-20 | tipo: DIP | symbol: BBVA.MC | sector: Financial Services
close: 17.92 | rsi_14: 48.14 | momentum_10d_pct: -1.67
recommendation_key: buy | score: 32.5 | dip_5d_pct: -2.18
```

---

### `report_opportunities_snapshot` — Señales de timing por símbolo
Vista con el último precio de cada símbolo activo. Clasifica cada acción según su valoración respecto a SMA200 y su momento de entrada según RSI + Bollinger.

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `symbol` | STRING | Ticker |
| `last_updated` | DATE | Última fecha disponible |
| `current_price` | FLOAT | Precio actual |
| `pct_vs_sma200` | FLOAT | % sobre/bajo la SMA200 |
| `valuation_status` | STRING | `GANGA HISTORICA`, `DESCUENTO`, `PRECIO JUSTO`, `NORMAL`, `SOBREVALORADA` |
| `rsi_14` | FLOAT | RSI actual |
| `bollinger_pct` | FLOAT | Posición en Bollinger (0-1) |
| `timing_signal` | STRING | `COMPRA FUERTE (Rebote)`, `ACUMULAR`, `MANTENER / OBSERVAR`, `NO COMPRAR (Esperar correccion)` |
| `long_term_trend` | STRING | `Bullish` o `Bearish` |
| `sma_200` | FLOAT | Valor absoluto de la SMA200 |
| `bollinger_low` | FLOAT | Banda inferior de Bollinger |
| `bollinger_high` | FLOAT | Banda superior de Bollinger |

**Ejemplo:**
```
symbol: BBVA.MC | current_price: 17.92 | pct_vs_sma200: 4.12
valuation_status: PRECIO JUSTO | timing_signal: MANTENER / OBSERVAR
long_term_trend: Bullish | rsi_14: 48.14
```

---

## Pipeline de actualización

```
Diario (lun-vie, Europe/Madrid):
  05:00 → daily_prices       (descarga precios OHLCV)
  05:30 → daily_enrich       (regenera enriched_prices_table)
  06:00 → daily_scanner      (actualiza war_dip_results)

Semanal (domingo):
  10:00 → weekly_companies   (refresca metadata empresas)

Las vistas (bullish_screener, daily_watchlist, report_opportunities_snapshot)
se recalculan automáticamente en cada consulta — siempre muestran datos frescos.
```
