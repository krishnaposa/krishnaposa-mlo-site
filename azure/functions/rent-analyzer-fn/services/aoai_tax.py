# services/aoai_tax.py
import os, json, logging
from typing import Optional, Dict, Any
from openai import AzureOpenAI

AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT", "https://stocks-ai.openai.azure.com/")
AZURE_OPENAI_API_KEY    = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_OPENAI_API_VER    = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

def _client() -> Optional[AzureOpenAI]:
    if not (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT):
        return None
    return AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VER,
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )

def ai_tax_estimate(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Ask AOAI to estimate property taxes (prior & current year) and surface basis/assumptions.
    Input payload can include:
      {
        "address": "...", "city": "...", "state": "GA", "zip": "...",
        "county": "DeKalb",
        "value": 325000,               # market/purchase value (strong signal)
        "assessed_value": 130000,      # if you already have it
        "millage_per_1000": 33,        # overrides default if provided
        "raw_assessor_text": "...",    # optional pasted text from county page to be parsed
        "owner_occupied": false        # investor vs homestead
      }
    Returns None if AOAI is not configured or fails.
    """
    client = _client()
    if not client:
        return None

    system = (
        "You are a property tax assistant. "
        "Given US address context, estimate prior and current year annual property taxes for a non-homestead investor scenario. "
        "Prefer concrete figures in the input; otherwise use realistic assumptions for the locality. "
        "Return ONLY JSON matching the schema. Keep numeric fields as numbers."
    )

    # JSON schema we want back
    schema = {
        "type": "object",
        "properties": {
            "prior_year": {"type": "number"},
            "prior_amount": {"type": "number"},
            "current_year_est": {"type": "number"},
            "basis": {
                "type": "object",
                "properties": {
                    "method": {"type": "string"},        # e.g. "assessed*millage", "rate_pct*value"
                    "assessed_value": {"type": "number"},
                    "assessment_ratio_pct": {"type": "number"},
                    "millage_per_1000": {"type": "number"},
                    "effective_rate_pct": {"type": "number"},
                    "notes": {"type": "string"}
                }
            },
            "exemptions_considered": {
                "type": "object",
                "properties": {
                    "homestead": {"type": "boolean"},
                    "other": {"type": "string"}
                }
            },
            "confidence": {"type": "string"}  # low|medium|high
        },
        "required": ["prior_year", "prior_amount", "current_year_est", "confidence"]
    }

    user = {
        "task": "estimate_property_tax",
        "inputs": payload,
        "schema": schema,
        "rules": [
            "Assume investor/non-homestead unless owner_occupied=true.",
            "If millage & assessment ratio are known, use assessed_value * (millage/1000).",
            "If only market value is known, use an effective rate percent based on locality norms.",
            "Infer prior_year from current calendar year minus one.",
            "If raw_assessor_text is present, extract any numbers and prefer them over assumptions."
        ]
    }

    try:
        resp = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user)}
            ],
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        logging.warning("AOAI tax estimate failed: %s", e)
        return None