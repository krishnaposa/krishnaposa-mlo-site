import yfinance as yf

yfinThisGood = {
    #"isBuyIncreasing": [True],
    "isCFOIncreasing": [True],
    "recommendation": ["buy","strong_buy"],
    "forwardPE": 25,
    "revenueGrowth": 0.2,
    "earningsGrowth": 0.2,
    "profitMargin": 0.2
}

def isBuyIncreasing(equity,lastHow=2):
   e = yf.Ticker(equity.symbol)
   #print(e.recommendations_summary)
   strongBuyList = e.recommendations_summary['strongBuy'][0:lastHow]
   isInc = all(j < i for i, j in zip(strongBuyList, strongBuyList[1:]))
   equity.isBuyIncreasing = isInc
   return equity

def isCFOIncreasing(equity,lastHow=2):
      e = yf.Ticker(equity.symbol)
      #print(e.quarterly_cashflow)
      cFlow = e.quarterly_cashflow.iloc[0][0:lastHow]
      isInc = all(j < i for i, j in zip(cFlow, cFlow[1:]))
      equity.isCFOIncreasing = isInc
      return equity


def update(equity):
      try:
            isCFOIncreasing(equity)
            isBuyIncreasing(equity)
            e = yf.Ticker(equity.symbol)
            equity.recommendation=  e.info['recommendationKey']
            equity.forwardPE = e.info['forwardPE']
            equity.revenueGrowth = e.info['revenueGrowth']
            equity.earningsGrowth = e.info['earningsGrowth']
            equity.profitMargin = e.info['profitMargins'];
      except Exception as e:
            pass

def filterForYFin(equityList, yFinDict):
   filterList = []
   
   for e in equityList:
       add = True
       if ( "isCFOIncreasing" in e.__dict__.keys() and  "isCFOIncreasing" in yFinDict.keys()):
           if(e.isCFOIncreasing  in yFinDict["isCFOIncreasing"]):
             add = True
           else:
             add = False
       if add and ("isBuyIncreasing" in e.__dict__.keys() and "isBuyIncreasing" in yFinDict.keys()):
          if( e.isBuyIncreasing in yFinDict["isBuyIncreasing"]):
             add = True
          else:
             add = False
       if add and ("recommendation" in e.__dict__.keys() and "recommendation" in yFinDict.keys()):
          if( e.recommendation in yFinDict["recommendation"]):
             add = True
          else:
             add = False
       if add and ("forwardPE" in e.__dict__.keys() and "forwardPE" in yFinDict.keys()):
            if( e.forwardPE <= yFinDict["forwardPE"] ):
                  add = True
            else:
                  add = False
       if add and ("revenueGrowth" in e.__dict__.keys() and "revenueGrowth" in yFinDict.keys()):
            if( e.revenueGrowth >= yFinDict["revenueGrowth"] ):
             add = True
            else:
             add = False
       if add and ("earningsGrowth" in  e.__dict__.keys() and "earningsGrowth" in yFinDict.keys()):
            if( e.earningsGrowth >= yFinDict["earningsGrowth"] ):
                  add = True
            else:
                  add = False
       if add and ("profitMargin" in e.__dict__.keys() and "profitMargin" in yFinDict.keys()):
            if( e.profitMargin >= yFinDict["profitMargin"] ):
                  add = True
            else:
                  add = False

       if(add):
          filterList.append(e)
   return filterList



