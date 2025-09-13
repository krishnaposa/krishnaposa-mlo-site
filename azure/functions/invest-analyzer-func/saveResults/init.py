try:
    from shared import cosmos
except ImportError:
    cosmos = None

def main(payload: dict):
    if not payload or "id" not in payload:
        return {"ok": False, "error": "Missing id in payload"}

    if cosmos:
        try:
            doc = cosmos.get_doc(payload["id"]) or {"id": payload["id"]}
            for k in ("pulls", "estimates", "metrics", "verdict", "reasons"):
                if k in payload:
                    doc[k] = payload[k]
            doc["status"] = "done"
            cosmos.upsert_doc(doc)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return {"ok": True, "note": "Cosmos not configured"}