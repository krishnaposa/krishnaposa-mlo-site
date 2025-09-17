# services/aoai.py
import os, json, logging
from openai import AzureOpenAI

AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT", "https://rent-analyzer-ai.openai.azure.com/")
AZURE_OPENAI_API_KEY    = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_OPENAI_API_VER    = os.getenv("AZURE_OPENAI_API_VERSION", "2024-11-20")

def _client() -> AzureOpenAI | None:
    if not (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT):
        return None
    return AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VER,
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )

def prefetch_estimate(inputs: dict, tax_block: dict | None) -> dict | None:
    """
    Ask AOAI for rent + expense estimates; JSON-only response.
    """
    client = _client()
    if not client: return None

    system = (
        "Estimate fair-market monthly rent (12+ months) and typical expenses. "
        "Return ONLY JSON with 'rent' and 'expenses' keys. Keep numbers numeric."
    )
    user = {
        "task": "rental_prefetch",
        "address": inputs.get("address"),
        "city": inputs.get("city"),
        "state": inputs.get("state"),
        "zip": inputs.get("zip"),
        "propertyType": inputs.get("propertyType") or "Unknown",
        "units": inputs.get("units") or 1,
        "hints": {
            "price_or_value": inputs.get("purchasePrice") or inputs.get("homeValue"),
            "known_taxes": tax_block or {}
        },
        "output_format": {
            "type": "object",
            "properties": {
                "rent": {"type":"object","properties":{
                    "est":{"type":"number"},"low":{"type":"number"},"high":{"type":"number"},
                    "confidence":{"type":"string"},"notes":{"type":"string"}
                },"required":["est"]},
                "expenses":{"type":"object","properties":{
                    "tax_prior_year":{"type":"object","properties":{
                        "year":{"type":"number"},"amount":{"type":"number"},"source":{"type":"string"}}},
                    "tax_current_year_est":{"type":"number"},
                    "insurance_annual_est":{"type":"number"},
                    "hoa_monthly_est":{"type":"number"},
                    "pm_pct_est":{"type":"number"},
                    "maint_pct_est":{"type":"number"},
                    "utilities_monthly_est":{"type":"number"},
                    "restriction_hint":{"type":"string"}
                },"required":["tax_current_year_est"]}
            },
            "required":["rent","expenses"]
        }
    }

    try:
        resp = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=[
                {"role":"system","content":system},
                {"role":"user","content":json.dumps(user)}
            ],
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        logging.warning("AOAI prefetch failed: %s", e)
        return None