# services/aoai_appreciation.py
import os, json, logging
from typing import Optional, Dict, Any
from openai import AzureOpenAI

AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT", "https://rent-analyzer-ai.openai.azure.com/")
AZURE_OPENAI_API_KEY    = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_OPENAI_API_VER    = os.getenv("AZURE_OPENAI_API_VERSION", "2024-11-20")

def _client() -> Optional[AzureOpenAI]:
    if not (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT):
        return None
    return AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VER,
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )

def ai_appreciation(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Ask AOAI to estimate annual appreciation % for long-term hold in this micro-market.
    Input can include: address/city/state/zip, propertyType, year_built, sqft, purchasePrice,
    local hints (schools/employment node, transit), and optional horizon years.
    Returns JSON like:
      {
        "annual_pct": 3.4,
        "confidence": "medium",
        "notes": "Historically ...",
        "projections": {
          "years": [1,3,5],
          "values": [222000, 236500, 252900]  # projected property values (compound growth)
        }
      }
    """
    client = _client()
    if not client: return None

    system = (
        "You are a real estate market assistant. "
        "Estimate a realistic *annual* appreciation rate for the subject property’s micro-market (owner-occupied resale, not construction), "
        "and provide projected values at 1/3/5 years using compound growth. "
        "Return ONLY JSON with numeric values."
    )
    schema = {
        "type":"object",
        "properties":{
            "annual_pct":{"type":"number"},
            "confidence":{"type":"string"},
            "notes":{"type":"string"},
            "projections":{"type":"object","properties":{
                "years":{"type":"array","items":{"type":"number"}},
                "values":{"type":"array","items":{"type":"number"}}
            }}
        },
        "required":["annual_pct","confidence"]
    }

    user = {
        "task":"estimate_appreciation",
        "schema":schema,
        "inputs":payload,
        "rules":[
            "Use local, long-run norms adjusted for the current macro backdrop.",
            "Prefer stability over extremes; avoid >8% long-run assumptions unless strongly justified.",
            "Compute projections with compound growth: value * (1+g)^t."
        ]
    }

    try:
        resp = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            temperature=0.0,
            response_format={"type":"json_object"},
            messages=[
                {"role":"system","content":system},
                {"role":"user","content":json.dumps(user)}
            ],
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        logging.warning("AOAI appreciation failed: %s", e)
        return None