# Stocks Function App Architecture

## Purpose

`stocks-func-app` is an Azure Functions Python app that builds a stock universe,
runs a daily quantitative monitor, sends a daily stock-picks email, persists
daily artifacts to Azure Blob Storage, and optionally ranks tickers with Azure
OpenAI.

The app is designed for scheduled batch execution with a few HTTP endpoints for
health checks, universe reads, manual universe refreshes, and ad hoc AI ranking.

## Runtime

- Platform: Azure Functions, Python v2 programming model
- Entry point: `function_app.py`
- Function host config: `host.json`
- Dependencies: `requirements.txt`
- Durable data: Azure Blob Storage
- Market data: Yahoo Finance / YahooQuery / Finviz-based utilities
- AI ranking: Azure OpenAI through `ai_utils.py`

## Main Components

```mermaid
flowchart TD
    TimerRefresh["Timer: refresh_universe"] --> UniverseBuilder["wb4u_main.get_universe or subprocess"]
    UniverseBuilder --> UniverseBlob["Blob: cache/universe.json"]

    TimerMonitor["Timer: monitor_signals"] --> Monitor["monitoring.monitor.run_monitor"]
    Monitor --> UniverseRead["Read universe cache"]
    Monitor --> LocalList["Read local list"]
    Monitor --> MarketData["Fetch Yahoo prices and metadata"]
    Monitor --> Features["Indicators, fundamentals, MC, HMM, ML"]
    Features --> Scoring["Quant scoring and buy flags"]
    Scoring --> Email["Email report"]
    Scoring --> SignalBlobs["Blob: daily snapshots and leaders"]

    TimerMonitor --> AIRank["Azure OpenAI ranking"]
    AIRank --> AIArtifacts["Blob: AI ranking JSON"]

    HttpUniverse["GET /universe"] --> UniverseBlob
    HttpRefresh["POST /refresh"] --> UniverseBuilder
    HttpRank["POST /rank"] --> AIRank
```

## Function Triggers

### `monitor_signals`

Scheduled by:

```text
0 30 23 * * 1-5
```

Runs on weekdays at 23:30 UTC. It:

1. Calls `daily_monitor.run_monitor`, which delegates to `monitoring.monitor.run_monitor`.
2. Fetches prices for the merged universe and local list.
3. Computes indicators, fundamentals, Monte Carlo probability, HMM regime
   probability, and ML probability.
4. Scores tickers and creates buy flags.
5. Sends the email report.
6. Writes daily parquet outputs to the `SIGNALS_CONTAINER` blob container.
7. Generates and persists Azure OpenAI ranking outputs.

### `refresh_universe`

Scheduled by:

```text
0 9 * * 1-5
```

Runs on weekdays at 09:00 UTC and also has `run_on_startup=True`.

It computes the stock universe using `WB4U_ENTRY`, defaulting to `wb4u_main.py`,
then stores the result in Blob Storage as `UNIVERSE_BLOB_NAME`, defaulting to
`universe.json`.

### `GET /health`

Anonymous health check. Returns:

```json
{"ok": true}
```

### `GET /universe`

Reads the cached universe from Blob Storage. If the cache is missing, it computes
and writes a new universe once. The response includes a `stale` flag based on
`UNIVERSE_TTL_MIN`.

### `POST /refresh`

Manually refreshes the universe. This route requires `REFRESH_SHARED_KEY` to be
set and supplied through either:

```text
x-refresh-key: <key>
```

or:

```text
?key=<key>
```

### `POST /rank`

Ranks supplied tickers with Azure OpenAI.

If `RANK_SHARED_KEY` is set, callers must provide either:

```text
x-rank-key: <key>
```

or:

```text
?key=<key>
```

Example request body:

```json
{
  "tickers": ["MSFT", "NVDA", "AAPL"],
  "strategy": "leaps",
  "horizon": "12-24 months"
}
```

## Daily Monitor Flow

```mermaid
sequenceDiagram
    participant Timer as Azure Timer
    participant App as function_app.py
    participant Monitor as monitoring.monitor
    participant Storage as Azure Blob Storage
    participant Yahoo as Yahoo/Finviz data
    participant OpenAI as Azure OpenAI
    participant Email as Email provider

    Timer->>App: monitor_signals
    App->>Monitor: run_monitor([])
    Monitor->>Storage: read universe and local list
    Monitor->>Yahoo: fetch prices and metadata
    Monitor->>Monitor: compute indicators and fundamentals
    Monitor->>Monitor: run Monte Carlo, HMM, and ML model
    Monitor->>Monitor: score rows and select picks
    Monitor->>OpenAI: rank LEAPS and debit call spread ideas
    Monitor->>Email: send daily report
    Monitor-->>App: df_all, df_leaders
    App->>Storage: write parquet snapshots
    App->>OpenAI: rank persisted AI artifacts
    App->>Storage: write AI JSON outputs
```

## Quant, Monte Carlo, HMM, and ML Design

### Feature Engineering

`monitoring.monitor.run_monitor` fetches roughly 420 calendar days of price
history. Per ticker it computes:

- Trend and flow: ADX, MFI, RSI, MACD histogram
- Returns: 1 day, 5 day, 20 day, 21 day, 60 day, 63 day, 120 day, 252 day
- Moving averages: 20 day, 50 day, 200 day
- Volatility: 20 day and 60 day realized volatility
- Relative volume: current volume versus 20 day average volume
- Breakout distance: distance from 52 week high
- Fundamentals: quarterly revenue and earnings trends, debt/equity, insider
  ownership, revenue growth, and earnings growth when available from Yahoo
- Liquidity and market-cap related fields

### Monte Carlo

`monitoring.simulations.mc_paths_prob_up` estimates the probability that a stock
finishes above the current price over 30 and 40 trading days. It uses daily drift
and volatility from recent returns and a geometric Brownian motion closed form.

Invalid inputs return `NaN`. Near-zero volatility is handled deterministically so
flat series do not create artificial failures.

### HMM Regime

`monitoring.simulations.fit_hmm_regime` fits a two-state Gaussian HMM on cleaned
daily returns. The state with the higher mean return is treated as the bull
state. If hmmlearn is unavailable, there is too little history, returns are flat,
or fitting fails, the function returns a neutral probability of `0.50`.

### ML Direction Model

`monitoring.model_predict.train_direction_model` trains a logistic-regression
classifier across all enriched ticker frames. The target is whether the forward
30 trading day return is non-negative.

If there is insufficient data or only one target class, the model falls back to a
dummy prior model. `predict_up_probability_for_latest` then produces the latest
available probability for each ticker.

## Wheel Cash-Secured Put Design

The wheel path is built inside `monitoring.monitor.run_monitor` after the main
quant scoring and ML probability are available. It is intended for 45-day
cash-secured put candidates, not long put buying.

### Equity Pre-Filter

The pre-filter uses only large, liquid, bullish or neutral quality stocks. The
default gates are configurable through environment variables:

```text
WHEEL_ENABLED=1
WHEEL_TOPK=8
WHEEL_PREFILTER_TOPN=40
WHEEL_MIN_MARKET_CAP=10000000000
WHEEL_MIN_PRICE=10
WHEEL_MAX_RSI=70
WHEEL_MIN_REL_VOLUME=1.2
WHEEL_MAX_DIST_52W_HIGH=0.05
WHEEL_MAX_DEBT_TO_EQUITY=1.0
WHEEL_MIN_INSIDER_OWNERSHIP=0.10
WHEEL_MIN_GROWTH=0.20
```

The filter requires:

- Price above `WHEEL_MIN_PRICE`.
- Market cap above `WHEEL_MIN_MARKET_CAP`.
- RSI below `WHEEL_MAX_RSI`.
- Close above the 20 day and 50 day moving averages.
- Within `WHEEL_MAX_DIST_52W_HIGH` of the 52 week high.
- Relative volume above `WHEEL_MIN_REL_VOLUME`.
- Debt/equity below `WHEEL_MAX_DEBT_TO_EQUITY`.
- Insider ownership above `WHEEL_MIN_INSIDER_OWNERSHIP`.
- Revenue growth, earnings growth, or growth streak above the growth threshold.

Debt/equity, insider ownership, revenue growth, and earnings growth come from
`monitoring.fundamentals.compute_company_profile`, which uses Yahoo's
`Ticker.info` fields when available. The code treats insider ownership as the
closest available proxy for employee ownership.

### Option Chain Selection

`monitoring.options_metrics.cash_secured_put_candidate` fetches the put chain,
chooses an expiry in the configured DTE window, and selects an out-of-the-money
put strike near the configured target:

```text
WHEEL_MIN_DTE=35
WHEEL_MAX_DTE=55
WHEEL_PUT_OTM_PCT=0.05
WHEEL_MIN_OI=500
WHEEL_MAX_SPREAD_PCT=0.15
WHEEL_BLOCK_EARNINGS=1
```

The returned wheel row includes:

```text
ticker, score, expiry, dte, spot, strike, credit, roc, ann_return,
breakeven, buffer, oi, volume, iv, spread, earnings_days
```

Candidates are excluded when open interest is too low, bid/ask spread is too
wide, or earnings are within `EARNINGS_BLOCK_DAYS` when earnings blocking is
enabled.

### Wheel Scoring and Email Output

`monitoring.scoring.score_wheel_put_row` ranks candidates using:

- Trend quality: above moving averages, close to 52 week high, RSI below 70.
- Volume and probability support: relative volume, ML probability, HMM bull
  probability.
- Growth quality: revenue or earnings growth.
- Option attractiveness: return on cash, annualized return, open interest, bid
  ask spread, and downside buffer.

The daily email renders the result in:

```text
Wheel Strategy: 45-Day Cash-Secured Puts
```

## Dedicated Finviz Email List

The daily email also includes a separate list for the custom Finviz screener:

```text
Finviz: Strong Buy Large Caps at All-Time High
```

This list is fetched by `wb4u_main.get_large_strongbuy_alltime_high_symbols` and
uses the filters from:

```text
an_recom_strongbuy, cap_largeover, fa_debteq_u1, fa_pe_u50,
ta_alltime_nh, ta_perf_1wup, ta_sma20_pa, ta_sma50_pa
```

The screener is sorted by P/E ascending, matching `o=pe` in the Finviz URL.
It is displayed separately from the main universe, stock picks, and wheel
candidates so it can be reviewed directly in the email.

## Azure OpenAI Design

The AI layer lives in `ai_utils.py`. It uses the Azure OpenAI Python SDK and the
chat completions API to rank a list of tickers for a requested trading strategy.
It does not train or host a local model. The app sends ticker symbols and
strategy instructions to an Azure OpenAI deployment, then expects a JSON response
with ranked tickers and short reasoning.

### Configuration

The client is created from environment variables:

```text
AZURE_OPENAI_ENDPOINT=<Azure OpenAI resource endpoint>
AZURE_OPENAI_API_KEY=<Azure OpenAI API key>
AZURE_OPENAI_DEPLOYMENT=<deployment name, used as the chat model>
AZURE_OPENAI_API_VERSION=2024-10-21
```

`AZURE_OPENAI_DEPLOYMENT` is passed as the `model` value in
`client.chat.completions.create(...)`. The actual model family depends on what is
deployed behind that Azure deployment name.

If endpoint, key, or deployment is missing, `score_with_azure_openai` raises a
configuration error. `ai_rank_tickers` catches AI failures and returns an empty
DataFrame so the scheduled monitor can continue.

### Call Sites

There are three AI ranking paths in the design, but the scheduled LEAPS and
debit-spread paths are currently commented out because they are not needed. The
HTTP route still uses the lower-level `score_with_azure_openai` helper directly.

1. Daily email ranking inside `monitoring.monitor.run_monitor`.
2. Daily artifact persistence inside `function_app.monitor_signals`.
3. Ad hoc HTTP ranking through `POST /rank`.

The daily email path previously called `ai_rank_tickers` twice in
`monitoring/monitor.py`; these calls are currently commented out:

```text
ai_rank_tickers(merged_tickers, strategy="leaps", horizon_text="12-24 months", top_k=AI_EMAIL_TOPK)
ai_rank_tickers(merged_tickers, strategy="debit_call_spread", horizon_text="30-40 days", top_k=AI_EMAIL_TOPK)
```

The persisted artifact path previously built a combined list from the cached
universe and local list, filtered out sub-penny-threshold names when prices were
available, then called `ai_rank_tickers` twice in `function_app.py`; this block is
currently commented out:

```text
ai_rank_tickers(combined, strategy="leaps", horizon_text="12-24 months", top_k=AI_TOPK)
ai_rank_tickers(combined, strategy="debit_call_spread", horizon_text="30-40 days", top_k=AI_TOPK)
```

The HTTP route `POST /rank` does not call `ai_rank_tickers`. It calls
`score_with_azure_openai` directly using the request body:

```json
{
  "tickers": ["MSFT", "NVDA", "AAPL"],
  "strategy": "leaps",
  "horizon": "12-24 months"
}
```

If `RANK_SHARED_KEY` is set, `/rank` requires either `x-rank-key` or `?key=...`.

In the current code, there are no active scheduled `ai_rank_tickers` calls. The
commented scheduled calls are:

```text
monitoring/monitor.py:
  ai_rank_tickers(..., strategy="leaps", top_k=AI_EMAIL_TOPK)
  ai_rank_tickers(..., strategy="debit_call_spread", top_k=AI_EMAIL_TOPK)

function_app.py:
  ai_rank_tickers(..., strategy="leaps", top_k=AI_TOPK)
  ai_rank_tickers(..., strategy="debit_call_spread", top_k=AI_TOPK)
```

### Prompt Contract

The system prompt instructs the model to act as an equity analyst, return only
JSON, rank provided tickers for the chosen strategy, and score each ticker on a
0-10 scale.

The user message is JSON containing:

- `strategy`: the requested strategy.
- `tickers`: the ticker list.
- `instructions`: strategy-specific guidance.
- `output_format`: a JSON-schema-like description of the desired object.
- `scoring_guidance`: score buckets for excellent, good, ok, and weak.
- `format_expectations`: valid JSON with concise thesis and risk text.
- `horizon`: included when a horizon is supplied.

The API call uses:

```text
temperature=0.3
response_format={"type": "json_object"}
```

JSON mode makes malformed natural-language output less likely, but the code still
parses the returned message with `json.loads`.

### Supported Strategies

`ai_utils._make_prompt` has first-class instructions for:

- `leaps`: long-dated call options, durable uptrend, 6-18 month catalysts,
  implied volatility, liquidity, and risk.
- `debit_call_spread`: 30-40 day debit call spreads, directional edge,
  near-term catalysts, liquid options, reasonable implied volatility, and
  targetable resistance.
- `short_term_options`: 1-8 week options setups, catalysts, IV crush risk,
  liquidity, and technicals.

Any other strategy string is accepted, but it falls back to a generic instruction:

```text
Evaluate '<strategy>' with clear, investable reasoning.
```

### Expected AI Response

The expected response shape is:

```json
{
  "strategy": "leaps",
  "horizon": "12-24 months",
  "ranked": [
    {
      "ticker": "MSFT",
      "score": 8.4,
      "thesis": "Concise bullish rationale.",
      "risks": "Concise risk summary.",
      "suggested_action": "Optional action text."
    }
  ],
  "notes": "Optional model notes."
}
```

`ai_rank_tickers` normalizes this into a DataFrame with:

```text
ticker, ai_score, thesis, risks, suggested_action
```

It sorts by `ai_score` descending, limits the result to `top_k`, and returns an
empty DataFrame if there are no tickers or the AI call fails.

### Email and Blob Outputs

The daily email uses only the ticker symbols from the AI results:

```text
AI: 30-40 Day Debit Call Spreads
AI: LEAPS (12-24 months)
```

The detailed `ai_score`, `thesis`, `risks`, and `suggested_action` fields are
preserved in Blob JSON artifacts:

```text
signals/ai_leaps_<yyyy-mm-dd>.json
signals/ai_debit_call_spreads_<yyyy-mm-dd>.json
```

### Important Limitations

- The AI prompt currently sends ticker symbols, strategy text, and horizon only.
  It does not send the computed quant features, fundamentals, Monte Carlo
  probability, HMM probability, ML probability, recent returns, or option-chain
  metrics.
- The model's reasoning can rely on its general market knowledge and whatever
  information the deployed model has access to internally, but it is not grounded
  in the app's latest fetched market data unless that data is added to the
  prompt.
- The scheduled monitor currently calls Azure OpenAI in both `run_monitor` for
  email lists and again in `monitor_signals` for persisted JSON artifacts. This
  can duplicate token usage for overlapping ticker lists.
- `/rank` can incur Azure OpenAI cost, so `RANK_SHARED_KEY` should stay enabled
  outside trusted local testing.

## Blob Storage Layout

Container names are configurable through environment variables.

Default universe cache:

```text
cache/universe.json
```

Default signals output:

```text
signals/daily_snapshot_<yyyy-mm-dd>.snappy.parquet
signals/leaders_<yyyy-mm-dd>.snappy.parquet
signals/ai_leaps_<yyyy-mm-dd>.json
signals/ai_debit_call_spreads_<yyyy-mm-dd>.json
signals/local_list.json
```

## Required App Settings

Set these in the Azure Function App configuration:

```text
FUNCTIONS_WORKER_RUNTIME=python
AzureWebJobsStorage=<storage connection string for the function host>
MONITOR_STORAGE=<storage connection string for universe/signals data>
```

Recommended:

```text
REFRESH_SHARED_KEY=<shared secret for POST /refresh>
RANK_SHARED_KEY=<shared secret for POST /rank>
UNIVERSE_CONTAINER=cache
UNIVERSE_BLOB_NAME=universe.json
SIGNALS_CONTAINER=signals
MIN_DOLLAR_VOL=1000000
PENNY_PRICE=5
AI_TOPK=10
QUIET_HTTP_LOGS=1
```

Required for Azure OpenAI ranking:

```text
AZURE_OPENAI_ENDPOINT=<endpoint>
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_DEPLOYMENT=<deployment name>
AZURE_OPENAI_API_VERSION=2024-10-21
```

Email settings are consumed by `monitoring.emailer`; keep those app settings in
Azure as well.

## Azure Update Procedure

Run commands from:

```powershell
cd "c:\pers\krishnaposa-mlo-site\azure\functions\stocks-func-app"
```

### 1. Confirm Azure CLI and Functions Core Tools

```powershell
az --version
func --version
```

If needed, sign in:

```powershell
az login
az account set --subscription "<subscription-id-or-name>"
```

### 2. Validate Locally

Create or activate a Python virtual environment, install dependencies, and run a
syntax check:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m py_compile function_app.py universe_utils.py monitoring\monitor.py monitoring\simulations.py monitoring\model_predict.py
```

Optional local function host:

```powershell
func start
```

For local Blob emulation, `local.settings.json` currently uses:

```json
{
  "AzureWebJobsStorage": "UseDevelopmentStorage=true"
}
```

Set `MONITOR_STORAGE` locally before testing storage-backed flows.

### 3. Update App Settings in Azure

Replace placeholders with your actual resource group and function app name:

```powershell
$resourceGroup = "<resource-group>"
$functionApp = "<function-app-name>"
```

Set or update runtime and storage settings:

```powershell
az functionapp config appsettings set `
  --resource-group $resourceGroup `
  --name $functionApp `
  --settings `
    FUNCTIONS_WORKER_RUNTIME=python `
    MONITOR_STORAGE="<storage-connection-string>" `
    REFRESH_SHARED_KEY="<refresh-key>" `
    RANK_SHARED_KEY="<rank-key>" `
    UNIVERSE_CONTAINER=cache `
    UNIVERSE_BLOB_NAME=universe.json `
    SIGNALS_CONTAINER=signals `
    MIN_DOLLAR_VOL=1000000 `
    PENNY_PRICE=5 `
    AI_TOPK=10 `
    QUIET_HTTP_LOGS=1
```

Set Azure OpenAI settings:

```powershell
az functionapp config appsettings set `
  --resource-group $resourceGroup `
  --name $functionApp `
  --settings `
    AZURE_OPENAI_ENDPOINT="<azure-openai-endpoint>" `
    AZURE_OPENAI_API_KEY="<azure-openai-key>" `
    AZURE_OPENAI_DEPLOYMENT="<deployment-name>" `
    AZURE_OPENAI_API_VERSION="2024-10-21"
```

Use Azure Key Vault references for secrets when possible.

### 4. Deploy Code

From the function app folder:

```powershell
func azure functionapp publish $functionApp
```

If deployment should build remotely:

```powershell
func azure functionapp publish $functionApp --build remote
```

### 5. Restart and Verify

```powershell
az functionapp restart --resource-group $resourceGroup --name $functionApp
```

Get the app host name:

```powershell
$hostName = az functionapp show `
  --resource-group $resourceGroup `
  --name $functionApp `
  --query defaultHostName `
  --output tsv
```

Check health:

```powershell
Invoke-RestMethod "https://$hostName/api/health"
```

Check universe:

```powershell
Invoke-RestMethod "https://$hostName/api/universe"
```

Manually refresh the universe:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "https://$hostName/api/refresh" `
  -Headers @{ "x-refresh-key" = "<refresh-key>" }
```

Test ranking:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "https://$hostName/api/rank" `
  -Headers @{ "x-rank-key" = "<rank-key>" } `
  -ContentType "application/json" `
  -Body '{"tickers":["MSFT","NVDA","AAPL"],"strategy":"leaps","horizon":"12-24 months"}'
```

### 6. Monitor Logs

Stream logs:

```powershell
az functionapp log tail --resource-group $resourceGroup --name $functionApp
```

Check Application Insights for timer execution failures, dependency failures,
OpenAI errors, storage errors, and timeout behavior.

## Operational Notes

- `refresh_universe` has `run_on_startup=True`, so deployment or restart may
  trigger an immediate universe rebuild.
- `POST /rank` can call Azure OpenAI and incur cost. Keep `RANK_SHARED_KEY` set.
- `MONITOR_STORAGE` is required for universe and signal storage.
- Large universes increase Yahoo fetch time, HMM/ML compute time, and OpenAI
  prompt size.
- The scheduled monitor sends email from inside `run_monitor`; deploy changes
  carefully if email configuration is live.

## Common Troubleshooting

### `MONITOR_STORAGE is not set`

Set `MONITOR_STORAGE` in Azure app settings and restart the app.

### `/refresh` returns `Forbidden`

Confirm `REFRESH_SHARED_KEY` in Azure and pass the same value as `x-refresh-key`
or `?key=...`.

### `/rank` returns `Forbidden`

Confirm `RANK_SHARED_KEY` in Azure and pass the same value as `x-rank-key` or
`?key=...`.

### AI ranking returns an error

Check `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`,
`AZURE_OPENAI_DEPLOYMENT`, and `AZURE_OPENAI_API_VERSION`.

### Timer does not run

Check that the Function App is not stopped, the storage account is reachable,
and the timer trigger appears in the Azure Portal Functions list.

