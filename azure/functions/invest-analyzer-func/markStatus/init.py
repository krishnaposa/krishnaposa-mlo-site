from datetime import datetime, timezone

try:
    from shared import cosmos
except ImportError:
    cosmos = None

ALLOWED_KEYS = {"status", "error", "pulls", "estimates", "metrics", "verdict", "reasons"}

def main(payload: dict):
    if not cosmos:
        return {"ok": True, "note": "cosmos helper not available"}
    if not payload or "id" not in payload:
        return {"ok": False, "error": "Missing id"}

    analysis_id = payload["id"]

    try:
        doc = cosmos.get_doc(analysis_id)
        if not doc:
            # Create a skeleton doc if it doesn't exist (avoid race failures)
            doc = {"id": analysis_id, "status": payload.get("status", "running"), "createdAt": _now()}

        # Shallow update of supported fields
        for k in ALLOWED_KEYS:
            if k in payload:
                doc[k] = payload[k]

        # Timestamps
        if "createdAt" not in doc:
            doc["createdAt"] = _now()
        doc["updatedAt"] = _now()

        cosmos.upsert_doc(doc)
        return {"ok": True}
    except Exception as e:
        # Preserve the error on the document if we can
        try:
            if doc:
                doc["status"] = "error"
                doc["error"] = str(e)
                doc["updatedAt"] = _now()
                cosmos.upsert_doc(doc)
        except Exception:
            pass
        return {"ok": False, "error": str(e)}

def _now():
    return datetime.now(timezone.utc).isoformat()