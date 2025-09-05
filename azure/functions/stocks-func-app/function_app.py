import azure.functions as func
import datetime
import json
import logging
import os, json, sys, tempfile, subprocess, shutil, logging
from openai import AzureOpenAI
GITHUB_REPO   = os.getenv("GITHUB_REPO", "github.com/krishnaposa/wb4u_stock_analysis.git")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "master")
WB4U_ENTRY    = os.getenv("WB4U_ENTRY", "wb4u_main.py")
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN")  # read-only PAT

AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT")  # e.g., https://myres.openai.azure.com
AZURE_OPENAI_API_KEY    = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")  # your chat deployment name
AZURE_OPENAI_API_VER    = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

app = func.FunctionApp()

def _clone_and_run() -> list[str]:
    tmp = tempfile.mkdtemp()
    try:
        repo_url = f"https://{GITHUB_TOKEN}:x-oauth-basic@{GITHUB_REPO}"
        subprocess.check_call([
            "git","clone","--depth","1","--branch",GITHUB_BRANCH,repo_url,tmp
        ])
        entry = os.path.join(tmp, WB4U_ENTRY)
        if not os.path.exists(entry):
            raise FileNotFoundError(f"Missing entry script: {entry}")

        run = subprocess.run([sys.executable, entry], check=True, capture_output=True, text=True)
        out = run.stdout.strip()
        try:
            tickers = json.loads(out)
        except json.JSONDecodeError:
            tickers = eval(out, {"__builtins__": {}}, {})  # accept Python list literal
        if not isinstance(tickers, (list, tuple)):
            raise ValueError("wb4u_main.py must print a list/JSON array")
        return [str(t).upper().strip() for t in tickers if str(t).strip()]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def _make_prompt(tickers, strategy: str, horizon_years: int):
    system = (
        "You are an equity analyst. Return ONLY JSON. Rank the provided tickers for the chosen strategy. "
        "Keep reasoning brief. No disclaimers."
    )
    user = {
        "task": "Rank stocks for the chosen strategy",
        "strategy": strategy,
        "horizon_years": horizon_years,
        "tickers": tickers,
        "output_format": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string"},
                "ranked": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string"},
                            "score": {"type": "number"},
                            "thesis": {"type": "string"},
                            "risks": {"type": "string"},
                            "suggested_action": {"type": "string"}
                        },
                        "required": ["ticker","score","thesis"]
                    }
                },
                "notes": {"type": "string"}
            },
            "required": ["strategy","ranked"]
        },
        "instructions": {
            "long_term": f"Evaluate long-term compounding and drawdown resilience over {horizon_years} years.",
            "leaps": "Evaluate suitability for LEAP calls: catalysts, IV/liquidity, trend, macro sensitivity.",
            "swing": "Evaluate 1–8 week swing potential and risk control."
        }.get(strategy, f"Evaluate strategy: {strategy}")
    }
    return system, user

def _score_with_azure_openai(tickers, strategy: str, horizon_years: int) -> dict:
    client = AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VER,
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )
    system, user = _make_prompt(tickers, strategy, horizon_years)
    resp = client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user)}
        ],
        temperature=0.3,
        response_format={"type": "json_object"}
    )
    return json.loads(resp.choices[0].message.content)


@app.route(route="stocks_http", auth_level=func.AuthLevel.FUNCTION)
def stocks_http(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    try:
        # Try to parse JSON body
        try:
            body = req.get_json()
        except ValueError:
            body = {}

        # Pull params from query string if not in body
        strategy = body.get("strategy") or req.params.get("strategy") or "long_term"
        horizon = int(body.get("horizon_years") or req.params.get("horizon_years") or "3")

        tickers = body.get("tickers")
        if tickers:
            tickers = [str(t).upper().strip() for t in tickers]
        else:
            tickers = ["AAPL","MSFT","NVDA"]  # fallback or call your wb4u_main.py here

        return func.HttpResponse(
            json.dumps({"ok": True, "strategy": strategy, "tickers": tickers}),
            mimetype="application/json"
        )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({"ok": False, "error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )