#!/usr/bin/env python3
"""One-off: rebuild pie_sector_map.txt from holdings-list.json."""
import json
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# Explicit ticker -> sector for holdings (first match wins when building from lists below)
SECTOR_TICKERS: dict[str, list[str]] = {
    "MEGA_TECH": [
        "AAPL", "MSFT", "AMZN", "GOOG", "META", "ORCL", "CRM", "NOW", "IBM", "SNOW",
        "SHOP", "SNAP", "PINS", "ROKU", "SPOT", "TWLO", "ZS", "OKTA", "PATH", "BILL",
        "DOCU", "WDAY", "VEEV", "MNDY", "HUBS", "PAYC", "PEGA", "FOUR", "GDDY", "PLTR",
        "TTD", "INOD", "NTNX", "RBRK", "CRWV", "S", "NET", "SAP", "NICE", "MANH",
        "KVYO", "TOST", "DUOL", "UBER", "PYPL", "EBAY", "CPNG", "GRAB", "SE", "MELI",
        "WDAY", "NOW", "ORCL", "CRM", "ADBE", "INTU", "TEAM", "ZM", "U", "XYZ",
    ],
    "AI_SEMI": [
        "AAOI", "ACLS", "ALAB", "AMAT", "AMBQ", "AMD", "AMKR", "AOSL", "ARM", "ASML",
        "ASX", "AVGO", "CDNS", "CRDO", "GFS", "ICHR", "KLAC", "LRCX", "LSCC", "MCHP",
        "MKSI", "MPWR", "MRAM", "MRVL", "MU", "MXL", "NVDA", "NVTS", "ONTO", "POET",
        "RMBS", "SIMO", "SMCI", "SNPS", "STM", "TSM", "TSEM", "TER", "UMC", "VICR",
        "WOLF", "AEHR", "APH", "SANM", "COHR", "LITE", "FN", "FORM", "QCOM",
    ],
    "SPACE_DEFENSE": [
        "ACHR", "ASTS", "AVAV", "BKSY", "DPRO", "KTOS", "LDOS", "LHX", "LUNR", "PL",
        "RKLB", "RDW", "RTX", "HEI", "AXON", "BWXT", "PSN", "DRS", "ESLT", "ISSC",
        "ONDS", "BBAI", "OUST", "VSAT", "SATS", "RDW", "LUNR", "RKLB",
    ],
    "QUANTUM": ["IONQ", "RGTI", "QBTS", "QUBT"],
    "STORAGE": ["STX", "WDC", "SNDK"],
    "CLOUD_SAAS": [
        "DOCN", "BAND", "MDB", "SNOW", "NTNX", "RBRK", "CRWV", "PATH", "S", "NET",
        "TWLO", "OKTA", "ZS", "BILL", "DOCU", "CFLT", "ESTC",
    ],
    "BIOTECH": [
        "ACLX", "ADMA", "ALNY", "ARWR", "BEAM", "BMRN", "BNTX", "CRSP", "EXEL", "GMAB",
        "HALO", "INSM", "JANX", "KOD", "LEGN", "NTLA", "NKTR", "NTRA", "OMER", "PCVX",
        "PHAT", "PODD", "REGN", "RXRX", "SRPT", "TGTX", "TVTX", "URGN", "VERV", "VRTX",
        "VKTX", "VTYX", "WVE", "IBRX", "IKT", "NERV", "PRLD", "PRAX", "SLNO", "SMMT",
        "TSHA", "TRVI", "ZTS", "AZN", "BMY", "ALMU", "AKAN", "SDGR", "TERN", "DMRA",
        "SPRB", "WVE", "LEGN", "BEAM", "CRSP", "NTLA", "MRNA",
    ],
    "HEALTHCARE_SERV": [
        "UNH", "THC", "OSCR", "ENSG", "SGRY", "DXCM", "IDXX", "ISRG", "RMD", "VEEV",
        "VLTO", "MCK", "ABBV", "HIMS", "TDOC", "OSCR", "CORT", "ENSG",
    ],
    "FINTECH": [
        "COIN", "HOOD", "SOFI", "PYPL", "UPST", "LMND", "MSTR", "GLXY", "AFRM", "ROOT",
        "SYF", "FI", "FICO", "ICE", "SPGI", "BLK", "ARES", "KKR", "RNR", "FHI", "FOUR",
        "AXP", "ROL", "FLYW", "UPWK", "BILL", "INTU",
    ],
    "ENERGY_OIL": [
        "FANG", "EQT", "TRGP", "KNTK", "VNOM", "EXE", "NRG", "VST", "CEG", "FTI", "FLR",
        "TRMD", "DAC", "EQT", "FANG", "TRGP", "KNTK",
    ],
    "NUCLEAR_URANIUM": ["OKLO", "SMR", "LEU", "UUUU", "NNE"],
    "SOLAR_CLEAN": ["ENPH", "FSLR", "CSIQ", "FLNC", "BE", "NEE", "SHLS"],
    "CRYPTO_MINERS": ["MARA", "IREN", "WULF", "CIFR", "CORZ", "APLD", "DGXX"],
    "CHINA_ADR": [
        "BABA", "PDD", "TCOM", "LI", "NIO", "XPEV", "YDDL", "ATAT", "EH", "TME", "BILI",
        "MELI", "SE", "GRAB", "CPNG", "BYDDF", "BYDDY", "ASND", "ATZAF", "PMRTY", "RNECY",
        "SFTBY", "LSRCY", "KRKNF", "FANUY",
    ],
    "CONSUMER": [
        "LULU", "DECK", "CAVA", "BROS", "OLLI", "WSM", "TJX", "HAS", "CHWY", "EAT", "CELH",
        "DKNG", "WMT", "ONON", "DECK", "LULU", "MHK", "HAS", "RVLV",
    ],
    "INDUSTRIAL": [
        "GE", "GEV", "ETN", "EMR", "ROK", "FIX", "PWR", "FTAI", "MLI", "RRX", "TDG", "DE",
        "JCI", "HWM", "IESC", "EMR", "ETN", "GBX", "FLR", "TRMB", "ROK", "FIX", "PWR",
        "MTZ", "FTAI", "MLI", "RRX", "TDG", "TRMB", "SYM", "SERV",
    ],
    "MATERIALS": ["ALB", "AXTI", "SQM", "UUUU", "LAC", "MP", "HL", "GFI", "ORLA", "TMQ", "UAMY", "AA"],
    "NETWORK": ["ANET", "CIEN", "LITE", "COHR", "LUMN", "TDS", "USM", "NOK", "TTMI", "CGNT", "CGNX"],
    "ADTECH": ["APP", "RDDT", "TTD", "ZETA"],
    "HARDWARE": ["DELL"],
    "CYBER": ["PANW", "FTNT", "ZS", "CRWD"],
    "TRAVEL": ["BKNG", "EXPE", "CCL", "UAL"],
    "MINING": ["AA", "LAC", "UUUU", "UAMY", "MP", "HL", "GFI", "SQM", "ORLA", "TMQ"],
    "EV_BATTERY": ["QS", "AMPX", "ABAT"],
    "ROBOTICS": ["ISRG", "SYM", "SERV"],
    "REAL_ESTATE": ["OPEN"],
    "AUTO": ["TSLA", "CVNA", "LI", "NIO", "XPEV", "GTX", "BYDDY", "BYDDF"],
    "LOGISTICS": ["XPO", "SAIA", "UAL"],
    "RETAIL": ["AMZN", "WMT", "OLLI", "WSM", "TJX", "EBAY"],
    "TELECOM": ["TDS", "USM", "NOK", "LUMN"],
    "INFRA": ["FLEX", "AGX", "NBIS", "CORZ", "MDA", "VRT", "FTAI", "PWR", "FIX", "FLNC"],
    "MEDIA": ["SPOT", "ROKU", "SNAP", "PINS", "RDDT", "BILI", "TME"],
    "INSURANCE": ["ROOT", "LMND", "RNR", "ROL"],
    "RENEWABLE_UTIL": ["NEE", "NRG", "VST", "CEG", "OKLO"],
    "DATA_CENTER": ["CORZ", "APLD", "NBIS", "IREN", "WULF", "CIFR", "MARA"],
    "MEME_SPEC": ["GME", "AMC", "OPEN", "BBAI", "SOUN", "BULL"],
    "OPTICS": ["LASR", "LPTH", "COHR", "LITE"],
    "PHARMA": ["NVO"],
    "MED_DEVICE": ["CLPT", "TMDX", "DXCM"],
    "FINTECH_EXTRA": ["SEZL", "STNE", "CRCL", "EWBC"],
    "INDUSTRIAL_EXTRA": ["AMSC", "RYCEY", "SBGSY", "IFF", "TREX", "LMB", "IRON", "TE", "AGPU"],
    "CHINA_EXTRA": ["GCT", "PONY", "WRD", "XNDU", "WYFI"],
    "BIOTECH_EXTRA": ["LQDA", "NBIX", "RVMD", "FTRE", "SLS", "TEM", "BTSG", "RPRX"],
    "TECH_MISC": ["IOT", "NUAI", "OSS", "PENG", "SN", "RXT"],
    "AUTO_EXTRA": ["CPRT", "EVEX"],
    "CONSUMER_EXTRA": ["BRUN", "HLF", "PLNT", "TKO"],
    "MATERIALS_EXTRA": ["AQMS", "USAR"],
    "INSURANCE": ["PLMR"],
    "REIT_HEALTH": ["DOC"],
    "ENERGY_EXTRA": ["NXT", "AGPU"],
}

def main() -> None:
    holdings_path = SCRIPT_DIR / "holdings-list.json"
    data = json.loads(holdings_path.read_text(encoding="utf-8"))
    holdings = sorted({str(t).upper().strip() for t in data.get("tickers", []) if str(t).strip()})

    assigned: dict[str, str] = {}
    for sector, tickers in SECTOR_TICKERS.items():
        for t in tickers:
            tu = t.upper()
            if tu in holdings and tu not in assigned:
                assigned[tu] = sector

    for t in holdings:
        if t not in assigned:
            assigned[t] = "OTHER"

    by_sector: dict[str, list[str]] = defaultdict(list)
    for t in holdings:
        by_sector[assigned[t]].append(t)

    lines = [
        "# Sector groups for pie_sector.py",
        "# Generated from holdings-list.json — edit sectors as you like.",
        "# Format:  SECTOR=TICKER1, TICKER2, TICKER3",
        "# Tickers in my_tickers.txt but not listed below get sector OTHER.",
        "",
    ]
    order = sorted(by_sector.keys(), key=lambda s: (s == "OTHER", s))
    for sector in order:
        tickers = sorted(by_sector[sector])
        lines.append(f"{sector}=" + ", ".join(tickers))

    out = SCRIPT_DIR / "pie_sector_map.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    other_n = len(by_sector.get("OTHER", []))
    print(f"Wrote {out.name}: {len(holdings)} tickers, {len(by_sector)} sectors, OTHER={other_n}")


if __name__ == "__main__":
    main()
