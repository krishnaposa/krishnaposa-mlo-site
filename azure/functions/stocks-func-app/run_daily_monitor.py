# run_daily_monitor.py
import datetime
import os
import logging
import daily_monitor  # our separate module

# ----------------------------------------------------------------------
# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# ----------------------------------------------------------------------
# Hardcoded list (same as in function app). 
# You could also import from a shared constants.py if you want.
LIST_TICKERS = [
    "META","TSM","ORCL","WMT","BABA","ABBV","PLTR","ASML","GE","UNH","SAP","IBM","AMD","AZN",
    "NVO","AXP","RTX","APP","MU","UBER","NOW","PDD","ANET","SHOP","LRCX","BKNG","BLK","AMAT",
    "GEV","TJX","ARM","ISRG","APH","KLAC","SPOT","ADBE","ETN","COF","PANW","BYDDF","CRWD","KKR",
    "MELI","SE","CEG","HOOD","VRTX","BMY","CDNS","MCK","ICE","DELL","MSTR","SNPS","RBLX","RACE",
    "RCL","MCO","COIN","HWM","AJG","SNOW","NET","EMR","TDG","MRVL","VST","JCI","FI","FTNT","ZTS",
    "PYPL","REGN","WDAY","PWR","COR","ALNY","CRWV","CPNG","LHX","STX","DDOG","ARES","IDXX","TCOM",
    "ZS","VEEV","CVNA","PMRTY","XYZ","MPWR","FANG","TEAM","CCL","EBAY","RMD","RDDT","HEI","TRGP",
    "GFI","FICO","TME","CSGP","EQT","MCHP","SYM","SOFI","ALAB","NRG","SMCI","INSM","CRCL","UAL",
    "FIX","ROL","PSTG","EXPE","NBIS","SYF","MDB","VLTO","LI","EXE","LPLA","DXCM","HUBS","AFRM",
    "CYBR","LDOS","BNTX","WSM","GRAB","FSLR","ESLT","RKLB","TTD","PINS","XPEV","TER","IOT","IONQ",
    "PODD","SATS","DG","TYL","TOST","BE","NTNX","RPRX","LULU","ASTS","DKNG","GMAB","GFS","GDDY",
    "TRMB","CTRA","NIO","COHR","THC","FTAI","AVAV","OKLO","FTI","TKO","RBRK","TWLO","CHWY","OKTA",
    "KTOS","DOCU","DECK","IFF","SMMT","ROKU","XPO","TEM","CELH","SN","SNAP","DUOL","NBIX","DOCS",
    "ONON","DOC","VNOM","HIMS","CRS","IREN","BAH","MANH","LSRCY","ASND","GLXY","RNR","DRS","PAYC",
    "NXT","EXEL","BILI","HAS","BMRN","RGTI","MNDY","LSCC","ENSG","PEGA","PSN","CORT","NICE",
    "KVYO","BLSH","MKSI","HALO","PLNT","BROS","CVLT","OLLI","MHK","SAIA","IESC","PONY","ELF","CAVA",
    "ROAD","FOUR","MARA","APLD","ONTO","USM","OPEN","SOUN","ACHR","PATH","RNA","SANM","LEGN","S",
    "CRSP","LEU","EAT","TGTX","UPST","BILL","BTSG","PI","SMR","ATAT","ENPH","PCVX","ZETA","STNE",
    "CALM","YOU","TDS","TMDX","FHI","QUBT","LMND","AGX","ADMA","DOCN","SLNO","VKTX","WRD","ACLS",
    "PLMR","DAVE","SEZL","SGRY","KNTK","AMSC","BBAI","IBRX","UPWK","AI","TVTX","IRON","RXRX","TRMD",
    "SRPT","DXPE","LQDA","DAC","NNE","RVLV","SDGR","GBX","JANX","ROOT","EH","LUNR","EVEX","NKTR",
    "TRVI","GCT","LMB","HLF","FTRE","FVRR","PHAT","EVER","AOSL","URGN","SERV","SRFM","DPRO","ELDN",
    "ATYR"
]

OUT_DIR = "out_local_monitor"
os.makedirs(OUT_DIR, exist_ok=True)

# ----------------------------------------------------------------------
def main():
    logging.info("=== Running local daily monitor ===")
    df_all, df_leaders = daily_monitor.run_monitor(LIST_TICKERS)

    stamp = datetime.date.today().strftime("%Y-%m-%d")
    csv_all = os.path.join(OUT_DIR, f"daily_snapshot_{stamp}.csv")
    csv_lead = os.path.join(OUT_DIR, f"leaders_{stamp}.csv")

    df_all.to_csv(csv_all, index=False)
    df_leaders.to_csv(csv_lead, index=False)

    logging.info(f"Saved {csv_all} and {csv_lead}")

    # Print a quick peek
    print("\nTop Picks Today:")
    print(df_all[df_all["buy_flag"]][["ticker", "score"]].head(12).reset_index(drop=True))

    print("\nLeaders (5d & 21d up):")
    print(df_leaders.head(15).reset_index(drop=True))

    logging.info("=== Done ===")


if __name__ == "__main__":
    main()