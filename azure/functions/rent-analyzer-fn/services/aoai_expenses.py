# services/aoai_expenses.py
import os, json, logging
from typing import Optional, Dict, Any
from openai import AzureOpenAI

AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY    = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_OPENAI_API_VER    = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

def _client() -> Optional[AzureOpenAI]:
    if not (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT):
        return None
    return AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VER,
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )

def ai_expense_pack(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Ask AOAI to estimate the full expense pack for a long-term rental (non-homestead).
    Input payload can include:
      address/city/state/zip/county, purchase/appraised value, assessed_value, millage_per_1000,
      propertyType, units, year_built, sqft, owner_occupied (bool), and any raw assessor text.
    Returns on success (JSON):
      {
        "tax": {
          "prior_year": 2024, "prior_amount": 3896, "current_year_est": 4025,
          "basis": { ... }, "exemptions_considered": { "homestead": false }, "confidence": "medium"
        },
        "insurance_annual_est": 1400,
        "hoa_monthly_est": 0,
        "utilities_monthly_est": 0,
        "pm_pct_est": 8,
        "maint_pct_est": 8,
        "restriction_hint": "Likely no HOA; verify CCRs.",
        "notes": "Brief rationale.",
        "confidence": "medium"
      }
    """
    client = _client()
    if not client: 
        return None

    system = (
        "You are a US rental underwriting assistant. "
        "Estimate the full operating expense pack for a long-term rental (investor, non-homestead). "
        "Prefer concrete inputs (assessed value, millage, prior bills). Otherwise use realistic local assumptions. "
        "Return ONLY JSON matching the schema. Keep numeric fields as numbers."
    )

    schema = {
        "type": "object",
        "properties": {
            "tax": {
                "type": "object",
                "properties": {
                    "prior_year": {"type": "number"},
                    "prior_amount": {"type": "number"},
                    "current_year_est": {"type": "number"},
                    "basis": {
                        "type": "object",
                        "properties": {
                            "method": {"type": "string"},
                            "assessed_value": {"type": "number"},
                            "assessment_ratio_pct": {"type": "number"},
                            "millage_per_1000": {"type": "number"},
                            "effective_rate_pct": {"type": "number"},
                            "notes": {"type": "string"}
                        }
                    },
                    "exemptions_considered": {
                        "type": "object",
                        "properties": {"homestead": {"type": "boolean"}, "other": {"type": "string"}}
                    },
                    "confidence": {"type": "string"}
                },
                "required": ["prior_year", "prior_amount", "current_year_est", "confidence"]
            },
            "insurance_annual_est": {"type": "number"},
            "hoa_monthly_est": {"type": "number"},
            "utilities_monthly_est": {"type": "number"},
            "pm_pct_est": {"type": "number"},
            "maint_pct_est": {"type": "number"},
            "restriction_hint": {"type": "string"},
            "notes": {"type": "string"},
            "confidence": {"type": "string"}
        },
        "required": ["tax", "insurance_annual_est", "pm_pct_est", "maint_pct_est"]
    }

    user = {
        "task": "estimate_all_expenses",
        "inputs": payload,
        "schema": schema,
        "rules": [
            "Assume investor/non-homestead unless owner_occupied=true.",
            "If assessment ratio & millage are present, compute taxes as assessed_value * (millage/1000).",
            "Otherwise estimate taxes via an effective property tax rate (%) of market value.",
            "Insurance should reflect typical hazard policy (no flood unless indicated).",
            "PM and Maintenance are % of monthly rent; provide reasonable local defaults.",
            "If HOA is unknown, return 0 and set restriction_hint accordingly."
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
        logging.warning("AOAI expense pack failed: %s", e)
        return None