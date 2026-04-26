import os, time, argparse, json, time as _time
import wb4u_yahooquery
import wb4u_yfinance
import wb4u_finviz

etfFilters = ['geo_usa','ind_exchangetradedfund','ta_rsi_nob60','ta_sma20_cross50a','ta_sma200_pa','ta_sma50_pa','sh_avgvol_o200000','sh_price_o10']

etfFilterPerf = ['ind_exchangetradedfund','ta_highlow20d_nh','ta_perf2_4wup','ta_sma20_pa','ta_sma200_pa','ta_sma50_pa','geo_usa','sh_avgvol_o200000','sh_price_o10']

etfNewHigh = ['geo_usa','ind_exchangetradedfund','ta_highlow52w_nh','sh_avgvol_o200000','ta_rsi_nob70']

etfTodayChange = ['ind_exchangetradedfund','sh_avgvol_o2000','ta_change_u1','ta_highlow20d_nh']
stocks_highGrowthFilter = ['an_recom_buybetter','fa_eps5years_o15','fa_epsqoq_o20','fa_epsyoy_o20','fa_epsyoy1_o20','fa_sales5years_o15','fa_salesqoq_o20','sh_instown_o30','sh_price_o15','geo_usa','fa_debteq_u1','ta_sma200_pa','sh_avgvol_o400']

stocks_smallCapFilter = ['cap_small','fa_eps5years_o20','fa_epsyoy_o20','fa_epsyoy1_o20','fa_estltgrowth_o20','sh_avgvol_o200','sh_curvol_o200','ta_sma200_pb','sh_price_o5','geo_usa']

stocks_longTermBuyHoldFilter = ['an_recom_buybetter','fa_debteq_u1','fa_div_o1','fa_eps5years_pos','fa_estltgrowth_o10','fa_roe_o15','fa_sales5years_o10','fa_salesqoq_pos','geo_usa','ipodate_more5','sh_short_u10','fa_pfcf_u25','fa_pe_low','ta_sma200_pa']

stocks_longTermBuyHoldFilter_2 = ['an_recom_buybetter','fa_debteq_u1','fa_div_o1','fa_eps5years_pos','fa_estltgrowth_o5','fa_roe_o15','fa_sales5years_o5','fa_salesqoq_pos','geo_usa','ipodate_more5','sh_short_u10','fa_pfcf_u25','fa_pe_low','ta_sma200_pa']
stocks_lowPEDividend1 = ['fa_debteq_u1','fa_div_o2','fa_estltgrowth_o5','fa_roe_o10','ind_stocksonly','sh_avgvol_o100','geo_usa','fa_pe_low','fa_payoutratio_u75']

stocks_lowPEDividend2 = ['cap_midover','fa_div_o3','fa_estltgrowth_pos','fa_payoutratio_u100','fa_pb_low','geo_usa','sh_avgvol_o100','fa_debteq_u1','fa_fpe_u20','ta_sma200_pa']

stocks_valueBeatsMarket = ['fa_eps5years_high','fa_ltdebteq_u0.5','fa_roe_o12','fa_roi_o10','fa_pb_u10','fa_pe_low','fa_pfcf_u25','fa_ps_u10','geo_usa','sh_price_o5','sh_avgvol_o400','ta_sma200_pa']

stocks_valueBeatsMarketAbove30ProfitMargin = ['fa_netmargin_o15','fa_eps5years_high','fa_ltdebteq_u0.5','fa_pb_u10','fa_pe_low','fa_pfcf_u25','fa_ps_u10','geo_usa','sh_price_o5','sh_avgvol_o400','ta_sma200_pa']
stocks_posNextYear = ['fa_epsqoq_o15','fa_epsyoy_neg','fa_epsyoy1_pos','fa_sales5years_o30','fa_salesqoq_o15','geo_usa','sh_instown_o10','ta_sma20_pa','ta_sma200_pa','ta_sma50_pa','fa_debteq_u1.5','sh_avgvol_o400','ta_rsi_nob70']

stocks_competitiveAdvantage = ['an_recom_buybetter','cap_midover','fa_peg_low','fa_roe_o20','geo_usa','sh_avgvol_o1000','sh_price_o10','ta_perf_4wup','ta_sma20_pa','targetprice_above','fa_grossmargin_o40']

stocks_bestPenny = ['an_recom_strongbuy','cap_microover','fa_debteq_low','sh_avgvol_o500','sh_price_u10','ta_beta_o0.5','geo_usa','sh_relvol_o1.5','ta_sma200_pa','sh_price_o2']

stocks_largeCapHighGrowth = ['cap_largeover','fa_eps5years_o15','fa_epsqoq_o5','fa_epsyoy1_o10','fa_estltgrowth_o10','fa_roe_o10','fa_sales5years_o10','fa_salesqoq_o5','geo_usa','sh_avgvol_o1000','sh_price_o10','ta_perf_4wup','ta_sma200_pa','fa_debteq_u1']

stocks_HighPerfNearHigh = ['cap_midover','fa_sales5years_pos','fa_salesqoq_o5','geo_usa','sh_avgvol_o800','ta_highlow52w_b0to5h','ta_perf_52w30o','ta_perf2_1wup','ta_sma20_pa','ta_rsi_nob70']

stocks_wedgeup = ['an_recom_buybetter','cap_large','fa_epsyoy1_high','geo_usa','sh_avgvol_o1000','ta_pattern_wedgeup2']

stocks_largeNewHighs = ['an_recom_buybetter','cap_largeover','fa_estltgrowth_pos','fa_sales5years_pos','sh_avgvol_o2000','sh_price_o5','ta_change_u','ta_highlow52w_nh','ta_perf_dup','targetprice_above','sh_relvol_o1.2']

stocks_highEarningsGrowth = ['cap_largeover','fa_epsqoq_o25','fa_epsyoy_o25','fa_epsyoy1_o25','fa_salesqoq_o25','sh_avgvol_o400','ta_rsi_nob70','ta_sma200_pa']

stocks_bestROE = ['an_recom_buybetter','cap_largeover','fa_epsyoy_o20','fa_epsyoy1_o20','fa_roe_o20','geo_usa','sh_avgvol_o1000','ta_perf_4wup','ta_perf2_1wup','fa_debteq_u1']

stocks_bestROEAndLarge = ['an_recom_buybetter','cap_largeover','fa_epsrev_bp','fa_epsyoy_pos','fa_epsyoy1_pos','fa_roe_o20','geo_usa','sh_avgvol_o1000','ta_highlow52w_b0to5h','ta_perf_dup','ta_perf2_1wup','ta_sma20_pa','fa_debteq_u1']

bestROEMid = ['an_recom_buybetter','cap_midover','fa_epsrev_bp','fa_epsyoy_o10','fa_epsyoy1_o10','fa_roe_o20','geo_usa','sh_avgvol_o1000','ta_highlow52w_b0to5h','ta_perf_dup','ta_perf2_1wup','ta_sma20_pa','fa_debteq_u1']

stocks_hightSalesGrowth = ['cap_largeover','fa_debteq_u0.5','fa_roe_o15','fa_sales5years_o20','fa_salesqoq_o20','sh_avgvol_o200','sh_instown_o60','sh_price_o5','sh_short_u5','ta_sma200_pa','fa_netmargin_o10']

stocks_highRelativeVol = ['cap_largeover','fa_curratio_o1','fa_epsqoq_o15','fa_quickratio_o1','fa_salesqoq_o15','sh_avgvol_o400','sh_price_o5','sh_relvol_o1.5','ta_sma20_pa','ta_sma50_sa200','ta_highlow20d_nh']

stocks_consistentGrowthBullingTrendAboveMid = ['cap_midover','fa_eps5years_pos','fa_epsqoq_o20','fa_epsyoy_o25','fa_epsyoy1_o15','fa_estltgrowth_pos','fa_roe_o15','sh_avgvol_o1000','sh_instown_o10','sh_price_o15','ta_highlow52w_a90h','ta_rsi_nob70']
largeNotOverboughtEarnRevbeatEPS5yrsPositive = ['an_recom_buybetter','cap_largeover','fa_epsrev_bp','fa_estltgrowth_pos','geo_usa','sh_avgvol_o1000','sh_opt_option','ta_highlow52w_b30h','ta_perf_dup','ta_perf2_1wup','ta_rsi_nob70','targetprice_above','ta_sma200_pa']

NotOverboughtRisingGood = ['an_recom_buybetter','cap_midover','fa_epsqoq_pos','fa_epsrev_bp','fa_salesqoq_pos','geo_usa','sh_avgvol_o1000','sh_opt_option','sh_relvol_o1.5','ta_perf_1wup','ta_rsi_nob70','targetprice_above']

cashflowEPSLarge = ['an_recom_buybetter','cap_largeover','fa_epsyoy1_o20','fa_netmargin_o20','fa_pfcf_u20','fa_roi_o10','sh_avgvol_o1000','ta_perf_dup','ta_perf2_1wup']

eps25WeekUpDayUpLarge = ['cap_largeover','fa_epsqoq_high','ta_perf2_13wup','ta_perf2_dup','ta_sma200_pa']

stock_from_insta_screener = ['cap_largeover','fa_epsyoy_o10','fa_fpe_u25','fa_peg_u2','fa_quickratio_o1.5','fa_roe_o5','geo_usa','fa_debteq_u1','sh_avgvol_o400','ta_sma200_pa']

stocks_large_strongbuy_alltime_high_value = ['an_recom_strongbuy','cap_largeover','fa_debteq_u1','fa_pe_u50','ta_alltime_nh','ta_perf_1wup','ta_sma20_pa','ta_sma50_pa']

def build_wheel_finviz_filters():
  """
  Build the wheel Finviz screener from env-configurable filter tokens.
  Set any value to empty to omit that Finviz filter.
  """
  filters = [
    os.getenv("WHEEL_FINVIZ_RECOMMENDATION_FILTER", "an_recom_buybetter"),
    os.getenv("WHEEL_FINVIZ_CAP_FILTER", "cap_largeover"),
    os.getenv("WHEEL_FINVIZ_DEBT_FILTER", "fa_debteq_u1"),
    os.getenv("WHEEL_FINVIZ_EPS_GROWTH_FILTER", "fa_epsqoq_o15"),
    os.getenv("WHEEL_FINVIZ_SALES_GROWTH_FILTER", "fa_salesqoq_o15"),
    os.getenv("WHEEL_FINVIZ_GEO_FILTER", "geo_usa"),
    os.getenv("WHEEL_FINVIZ_AVG_VOLUME_FILTER", "sh_avgvol_o1000"),
    os.getenv("WHEEL_FINVIZ_OPTIONABLE_FILTER", "sh_opt_option"),
    os.getenv("WHEEL_FINVIZ_PRICE_FILTER", "sh_price_o10"),
    os.getenv("WHEEL_FINVIZ_REL_VOLUME_FILTER", "sh_relvol_o1.2"),
    os.getenv("WHEEL_FINVIZ_HIGH_FILTER", "ta_highlow52w_b0to10h"),
    os.getenv("WHEEL_FINVIZ_PERF_FILTER", "ta_perf_1wup"),
    os.getenv("WHEEL_FINVIZ_RSI_FILTER", "ta_rsi_nob70"),
    os.getenv("WHEEL_FINVIZ_SMA20_FILTER", "ta_sma20_pa"),
    os.getenv("WHEEL_FINVIZ_SMA50_FILTER", "ta_sma50_pa"),
  ]
  return [f for f in filters if f]

stocks_wheel_cash_secured_puts = build_wheel_finviz_filters()

goodFilter = {
    "isCFOIncreasing": [True],
    "recommendation": ["buy","strong_buy"],
    "forwardPE": 25,
    "revenueGrowth": 0.2,
    "earningsGrowth": 0.2,
    "profitMargin": 0.2
}

def finviz_query(filters, sortOrder='-change'):
  return {"filters": filters, "sortOrder": sortOrder}

finviz_options=[
  finviz_query(stocks_large_strongbuy_alltime_high_value, sortOrder='pe'),
  stock_from_insta_screener,
  eps25WeekUpDayUpLarge,
  stocks_bestROEAndLarge,
  stocks_bestROE,
  stocks_posNextYear,
  stocks_competitiveAdvantage,
  stocks_HighPerfNearHigh,
  stocks_wedgeup,
  stocks_largeNewHighs,
  stocks_highEarningsGrowth,
  stocks_hightSalesGrowth,
  stocks_highRelativeVol,
  stocks_consistentGrowthBullingTrendAboveMid,
  largeNotOverboughtEarnRevbeatEPS5yrsPositive,
  NotOverboughtRisingGood
]

def get_large_strongbuy_alltime_high_symbols(max_count=25):
  """
  Dedicated list for the Finviz query:
  strong buy, large cap, debt/equity < 1, P/E < 50, all-time new high,
  1-week up, above SMA20 and SMA50, sorted by P/E ascending.
  """
  symbols = wb4u_finviz.getStocksSymbols(
    stocks_large_strongbuy_alltime_high_value,
    sortOrder='pe'
  )
  return [s.upper() for s in symbols[:max_count]]

def get_wheel_finviz_symbols(max_count=25):
  """
  Dedicated Finviz source for wheel candidates:
  large optionable stocks, price > 10, high relative volume, RSI not overbought,
  above SMA20/SMA50, near 52-week high, debt/equity < 1, and strong recent growth.
  """
  symbols = wb4u_finviz.getStocksSymbols(
    build_wheel_finviz_filters(),
    sortOrder=os.getenv("WHEEL_FINVIZ_SORT", "-change")
  )
  return [s.upper() for s in symbols[:max_count]]

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
        if isinstance(finviz_scr, dict):
          filters = finviz_scr.get("filters", [])
          sort_order = finviz_scr.get("sortOrder", "-change")
        else:
          filters = finviz_scr
          sort_order = "-change"
        symList = wb4u_finviz.getStocksSymbols(filters, sortOrder=sort_order)
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