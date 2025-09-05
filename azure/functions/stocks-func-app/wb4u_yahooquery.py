from yahooquery import Ticker
from yahooquery import get_trending
import json

def getHoldings(symbol):
  e = Ticker(symbol)
  
  res = []
  try:
    sym  =  e.fund_top_holdings.to_json(orient='records')
    symJson =  json.loads(sym)
    res = [ sub['symbol'] for sub in symJson if sub['symbol'] and sub['symbol'].isalpha()]
  except:
    pass
  return res

def getTrendingSymbols():
  json  =  get_trending()['quotes']
  res =  [sub['symbol']  for sub in json if sub['symbol'].isalpha() ]
  return res

