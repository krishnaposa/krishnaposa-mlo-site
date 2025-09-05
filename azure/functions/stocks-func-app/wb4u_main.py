import os, time, argparse, json, time as _time
import wb4u_yahooquery
import wb4u_yfinance
import wb4u_finviz

# --- your existing filters here (unchanged) ---
# (paste all filters from your version)
# ... [omitted here for brevity in this message] ...

# Keep your originals:
goodFilter = {
    "isCFOIncreasing": [True],
    "recommendation": ["buy","strong_buy"],
    "forwardPE": 25,
    "revenueGrowth": 0.2,
    "earningsGrowth": 0.2,
    "profitMargin": 0.2
}

finviz_options=[stock_from_insta_screener,eps25WeekUpDayUpLarge,stocks_bestROEAndLarge,stocks_bestROE,stocks_posNextYear,stocks_competitiveAdvantage,stocks_HighPerfNearHigh,stocks_wedgeup,stocks_largeNewHighs,stocks_highEarningsGrowth, stocks_hightSalesGrowth, stocks_highRelativeVol, stocks_consistentGrowthBullingTrendAboveMid, largeNotOverboughtEarnRevbeatEPS5yrsPositive, NotOverboughtRisingGood]

BEST_ETF_LIST=['OGIG','PTH','PTF','FXU','DFE','IQIN','SILJ','SGDJ','JKK','ARKW','ARKK','OGIG','ARKQ','BOTZ','IRBO','BLCN','BLOK','KOIN','BUG','CIBR','IHAK','XNTK','QQQ','IGM','HERO','ESPO','BJK','SMH','SOXX','PSI','TAN','PBW','QCLN','MLPX','AMLP','MLPA','QCLN','PBW','TAN','ARKG','PTH','KURE','BTEC','IDNA','XPH','IHE','CARZ','JETS','IYT','FTXR','XTN','IYK','ECON','PSL','VOX','FCOM','IXP','KRE','IAT','KBE','ITB','XHB','PKB','FAN','EDEN','GRID','IFRA','NFRA','TOLZ','YOLO','CNBS','THCX','INDS','XLRE','ICF','PHO','PIO','FIW','PFFD','EPRF','PGF','CHIQ','SPUU','SSO','UPRO','SPXL']
MID_GROWTH_ETF=['SFYF','CWS','MID','JKH','IVOG','ARKK','IJK','IPO','IWP','KOMP','MDYG','VOT','XMMO']
SMALL_GROWTH_ETF=['DWAS','DWMC','FYC','IJT','IWO','JKK','JSML','MFMS','PQSG','RZG','SLYG','SMCP','SPAK','SPCX','SPXZ','VBK','VIOG','VTWG','XSHQ','XSMO']
DISRUPT_ETF=['VGT','IETC','PSCT','ARKK','SOXX','FDN','FINX','EDOC','THNQ','ARKW','KWEB','EMQQ','NERD','WFH','FCOM','DTEC','SNSR','ARKQ','HTEC','BUG','ARKG']
LG_GROWTH_ETF=['ONEQ','IWY','TMFC','MGK','HIPR','IVW','PTNQ','IUSG','IVW','IWF','MTUM','QQQJ','SCHG','SPYG','VUG']

# --- helpers (unchanged from your version) ---
def getHoldingsEfts(ETF_LIST=BEST_ETF_LIST,topCount=2):
   holdings = []
   for etf in ETF_LIST:
      holdList = [e for e in wb4u_yahooquery.getHoldings(etf)]
      holdings.extend(holdList[0:topCount])
   return list(set(holdings))

def generateStockListForBestETFs():
  finalEList = []
  finalEFullList = []
  lst = [BEST_ETF_LIST,MID_GROWTH_ETF,LG_GROWTH_ETF,DISRUPT_ETF]
  for etfList in lst:
    equityList = getHoldingsEfts(etfList)
    equityListSmall = equityList[0:3]
    finalEList.extend(equityListSmall)
    finalEFullList.extend(equityList)
  eList = list(set(finalEList))
  eListFull = list(set(finalEFullList))
  return eList,eListFull

def findAllBestStocksWithSymbols(FINVIZ_LIST=finviz_options, sleep_sec=2, max_filters=None, time_left=lambda: 9999):
  symListAll, symListFull = [], []
  count = 0
  for finviz_scr in FINVIZ_LIST:
     if max_filters and count >= max_filters:
        break
     if time_left() < sleep_sec + 2:
        break
     try:
        time.sleep(sleep_sec)
        symList = wb4u_finviz.getStocksSymbols(finviz_scr, sortOrder='-change')
        symListSmall = symList[0:2]
        if symListSmall:
           symListAll.extend(symListSmall)
           symListFull.extend(symList)
        count += 1
     except Exception:
        pass
  return symListAll, symListFull

def createEquityListFromSymbols(symbolList):
    equityList = []
    for i in symbolList:
       e = wb4u_finviz.Equity(i)
       equityList.append(e)
    return equityList

def createSymbolListFromEquityList(equityList):
    return [e.symbol for e in equityList]

# --- main entry with budget ---
def get_universe(max_seconds=None):
    """
    Returns a list of tickers quickly. Obeys a soft time budget.
    If time is low, skips Finviz and uses ETF holdings (and trending) to still return results.
    """
    budget = float(max_seconds or os.getenv("WB4U_MAX_SECONDS") or 60)
    t0 = _time.time()
    def time_left():
        return budget - (_time.time() - t0)

    os.environ['DISABLE_TQDM'] = '1'

    # 1) Try building from Finviz (limited by time)
    use_finviz = time_left() > 15   # require at least 15s remaining
    symListDups = []
    if use_finviz:
        max_filters = 6 if budget >= 60 else 3
        symListAll, symListFull = findAllBestStocksWithSymbols(
            FINVIZ_LIST=finviz_options,
            sleep_sec=2,
            max_filters=max_filters,
            time_left=time_left
        )
        symListDups.extend(symListAll)

    # 2) Always add ETF holdings (fast) if time allows
    if time_left() > 5:
        eFromEtfs, eFromEtfsFull = generateStockListForBestETFs()
        symListDups.extend(eFromEtfs)

    # 3) If still thin or time nearly out, add Yahoo trending
    if len(symListDups) < 5 or time_left() < 5:
        try:
            symListDups.extend(wb4u_yahooquery.getTrendingSymbols())
        except Exception:
            pass

    # Unique
    symListDups = list({s.upper() for s in symListDups})

    # 4) Enrich with yfinance (guarded by remaining time)
    equityList = createEquityListFromSymbols(symListDups)
    for e in equityList:
        if time_left() < 5:
            break
        try:
            wb4u_yfinance.update(e)
        except Exception:
            pass

    # 5) Filter by yfinance metrics
    finalFilteredList = wb4u_yfinance.filterForYFin(equityList, goodFilter)
    symList = createSymbolListFromEquityList(finalFilteredList)

    # Fallback if filter too strict
    if not symList:
        symList = symListDups[:20]

    return [s.upper() for s in symList]

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--max-seconds", type=int, default=int(os.getenv("WB4U_MAX_SECONDS", "60")))
    args = p.parse_args()
    out = get_universe(max_seconds=args.max_seconds)
    print(json.dumps(out))