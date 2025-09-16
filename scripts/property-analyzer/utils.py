# utils.py
import os, re, json

from constants import DUMP_DIR

def log(s):  print(f"[INFO] {s}", flush=True)
def warn(s): print(f"[WARN] {s}", flush=True)

def to_float(x):
    if x is None: return None
    try:
        return float(re.sub(r"[^\d.\-]", "", str(x)))
    except Exception:
        return None

def clean_str(x):
    if x is None: return None
    s = str(x).strip()
    return s or None

def deep_find_keys(obj, keys_lower:set[str]):
    out = {}
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                kl = str(k).lower()
                if kl in keys_lower and kl not in out:
                    out[kl] = v
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return out

def normalize_hoa(val):
    v = to_float(val)
    if v is None: return None
    if v <= 0 or v > 5000:
        return None
    return v

def ensure_dump_dir():
    try: os.makedirs(DUMP_DIR, exist_ok=True)
    except Exception: pass

def dump_json_blob(idx: int, url: str, payload):
    ensure_dump_dir()
    path = os.path.join(DUMP_DIR, f"blob_{idx:02d}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"source_url": url, "json": payload}, f, indent=2)
        log(f"Dumped JSON blob #{idx} → {path}")
    except Exception as e:
        warn(f"Failed to dump blob #{idx}: {e}")

def dump_index(meta: dict):
    ensure_dump_dir()
    path = os.path.join(DUMP_DIR, "_index.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        log(f"Wrote dump index → {path}")
    except Exception as e:
        warn(f"Failed to write dump index: {e}")

def parse_k_amount(tok: str) -> float | None:
    if tok is None: return None
    tok = tok.strip().lower()
    if tok.endswith('k'):
        base = to_float(tok[:-1])
        return base * 1000 if base is not None else None
    return to_float(tok)

def rent_from_payload_url(u: str) -> tuple[float|None, float|None]:
    if not isinstance(u, str): return (None, None)
    m1 = re.search(r"(?:^|[?&,])min[-_]?price=([^&,]+)", u, re.I)
    m2 = re.search(r"(?:^|[?&,])max[-_]?price=([^&,]+)", u, re.I)
    lo = parse_k_amount(m1.group(1)) if m1 else None
    hi = parse_k_amount(m2.group(1)) if m2 else None
    return (lo, hi)

def extract_zip_from_any(s: str):
    m = re.search(r"\b(\d{5})(?:-\d{4})?\b", s or "")
    return m.group(1) if m else None