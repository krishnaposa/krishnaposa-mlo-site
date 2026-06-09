#!/usr/bin/env python3
"""Set site contact phone to 6784818252."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPLS = [
    ("tel:+18134211892", "tel:+16784818252"),
    ("sms:+18134211892", "sms:+16784818252"),
    ('"+18134211892"', '"+16784818252"'),
    ("+1-813-421-1892", "+1-678-481-8252"),
    ("wa.me/18134211892", "wa.me/16784818252"),
    ("tel:8134211892", "tel:6784818252"),
    (">813.421.1892<", ">6784818252<"),
    ("P: <a href=\"tel:8134211892\">813.421.1892</a><br>\n          F: 727.489.9504",
     "<a href=\"tel:6784818252\">6784818252</a>"),
    ('"faxNumber": "+17274899504",\n        ', ""),
    ('"faxNumber": "+17274899504",\n', ""),
]

count = 0
for path in ROOT.rglob("*.html"):
    if ".venv" in path.parts:
        continue
    text = path.read_text(encoding="utf-8")
    original = text
    for old, new in REPLS:
        text = text.replace(old, new)
    if text != original:
        path.write_text(text, encoding="utf-8", newline="\n")
        count += 1
        print(path.relative_to(ROOT))

print(f"updated {count} files")
