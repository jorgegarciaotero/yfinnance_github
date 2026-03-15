# yFinance GCP

Pipeline de datos financieros que descarga precios e indicadores de Yahoo Finance, los almacena en BigQuery y aplica un scanner cuantitativo para detectar oportunidades de entrada en valores con uptrend consolidado que han corregido por factores macro.

## Arquitectura

```
Yahoo Finance (yfinance)
        │
        ├─ weekly_companies  ──► companies              (metadata + fundamentales)
        └─ daily_prices      ──► daily_prices            (OHLCV diario)
                                        │
                                 daily_enrich  ──────────────────────────────────────►  enriched_prices_table
                                   (enrich_prices.bsql)                                 (precios + indicadores técnicos)
                                                                                                 │
                                                                                         daily_scanner ──► war_dip_results
                                                                                         (war_dip_scanner.bsql)
```

**Stack:** Python 3.11+ · BigQuery (google-cloud-bigquery) · GitHub Actions

---

## Jobs

| Job | Frecuencia | Descripción |
|-----|-----------|-------------|
| `weekly_companies` | Semanal (domingo) | Refresca el universo de empresas: valida disponibilidad en Yahoo Finance y guarda metadata (sector, market cap, ratios, recomendación de analistas). MERGE por `(symbol, updated_at)`. |
| `daily_prices` | Diario (lun–vie) | Descarga precios OHLCV. Si la tabla está vacía hace backfill de 5 años; si ya tiene datos, carga solo la fecha solicitada. MERGE por `(date, symbol)`, nunca duplica. |
| `daily_enrich` | Diario, tras `daily_prices` | Regenera `enriched_prices_table` ejecutando `enrich_prices.bsql`: calcula RSI, SMA, MACD, Bollinger, momentum y une con fundamentales. |
| `daily_scanner` | Diario, tras `daily_enrich` | Ejecuta el War Dip Scanner y guarda resultados en `war_dip_results` con MERGE por `(run_date, symbol)`. |

---

## War Dip Scanner

Detecta valores con **uptrend consolidado** (Bullish en 3m, 6m y 1y) que han **corregido por factores macro** (caída gradual del 2–40% en 5 días), con market cap ≥ $2B.

Cada valor recibe un **score 0–100**:

| Componente | Pts | Criterio |
|-----------|-----|---------|
| A1 — Rendimiento 1 año previo al dip | 15 | Normalizado entre 10% y 300% |
| A2 — Rendimiento 6 meses previo | 15 | Normalizado entre 5% y 150% |
| B1 — Magnitud del dip en 5d | 15 | Sweet spot −8% a −20% (pico en −14%) |
| B2 — Gradualidad de la caída | 10 | Caída progresiva = macro; caída en 1 día = evento puntual |
| C1 — RSI sobrevendido | 12 | RSI 20 → 12 pts, RSI 50 → 0 pts |
| C2 — Posición en Bollinger | 8 | Cercano a la banda inferior |
| D — Distancia a SMA200 | 15 | Salud estructural (log-normalizada) |
| E — Consenso de analistas | 10 | `strong_buy`=10, `buy`=7, `hold`=3 |

Los resultados se acumulan diariamente en `war_dip_results` para monitorizar la evolución de cada valor a lo largo del tiempo.

---

## Tablas BigQuery

| Tabla | Descripción |
|-------|-------------|
| `companies` | Metadata y fundamentales, 1 fila por semana por símbolo |
| `daily_prices` | Precios OHLCV diarios |
| `enriched_prices_table` | Precios + indicadores técnicos + fundamentales |
| `war_dip_results` | Snapshot diario del scanner con score desglosado |

---

## Requisitos

- Python 3.11+
- Proyecto GCP con BigQuery habilitado
- Credenciales GCP: `gcloud auth application-default login` o `service-account.json` en `src/config/`

```bash
pip install -r requirements.txt
```

---

## Configuración

```bash
cp .env.example .env
# Añadir YOUTUBE_API_KEY y ANTHROPIC_API_KEY si se usa ai_analyst
```

Las credenciales de GCP se resuelven en este orden:
1. `src/config/service-account.json` (si existe y contiene una clave válida)
2. `GOOGLE_APPLICATION_CREDENTIALS` del entorno
3. `gcloud auth application-default login`

---

## Uso

```bash
# Actualizar universo de empresas (semanal)
python -m src.jobs.weekly_companies

# Descargar precios (diario)
python -m src.jobs.daily_prices                  # ayer
python -m src.jobs.daily_prices 2025-01-15       # fecha concreta
python -m src.jobs.daily_prices 2025-01-01 2025-01-31  # rango

# Regenerar tabla enriquecida
python -m src.jobs.daily_enrich

# Ejecutar el scanner
python -m src.jobs.daily_scanner

# Limitar a N empresas (pruebas)
python -m src.jobs.weekly_companies 5
```

### Orden de ejecución

```
domingo:   weekly_companies → daily_enrich
lun–vie:   daily_prices → daily_enrich → daily_scanner
```

---

## GitHub Actions

Los pipelines se ejecutan automáticamente:

- **Daily** (`daily.yml`): lunes a viernes a las 06:00 UTC — `daily_prices` → `daily_enrich` → `daily_scanner`
- **Weekly** (`weekly.yml`): domingos a las 06:00 UTC — `weekly_companies` → `daily_enrich`

Las credenciales GCP se inyectan desde el secret `GCP_SERVICE_ACCOUNT_KEY` (Settings → Secrets → Actions).

---

## Variables de entorno

| Variable | Usado por | Descripción |
|----------|-----------|-------------|
| `YOUTUBE_API_KEY` | `ai_analyst` | YouTube Data API v3 |
| `ANTHROPIC_API_KEY` | `ai_analyst` | Claude API key |
