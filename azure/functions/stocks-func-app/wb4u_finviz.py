import requests
from jsonpath_rw import jsonpath
import json
import jsonpath_rw_ext as jp
from finviz.screener import Screener
import sys, traceback
from collections import namedtuple
from json import JSONEncoder
from collections import OrderedDict

def jsonDefault(OrderedDict):
    return OrderedDict.__dict__

class Equity:
    def __init__(self, symbol):
        self.symbol = symbol
    def __repr__(self):
       return json.dumps(self, default=jsonDefault, indent=4)
    def toJSON(self):
       return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True, indent=4)
    def serialize(obj):
       if isinstance(obj, date):
           serial = obj.isoformat()
           return serial
       if isinstance(obj, time):
           serial = obj.isoformat()
           return serial
       return obj.__dict__
    def createFromJson(self, json):
       self.__dict__ = json

portfolio =  [];
def getEtfs(etfFilters,sortOrder='price'):
  stock_list = Screener(filters=etfFilters, table='Valuation', order=sortOrder) 
  etfList = []
  for stock in stock_list: 
    equity = Equity(stock['Ticker'])
    equity.equityType = 'etf'
    portfolio.append(equity)
    etfList.append(stock['Ticker'])
  return portfolio,etfList

#cap:smallCapFilter,longTermBuyHoldFilter,lowPEDividend1,lowPEDividend2,valueBeatsMarket,goodFundamentals,competitiveAdvantage,bestPenny
def getStocks(cap,sortOrder='-epsyoy1'):
  try:
    stock_list = Screener(filters=cap, table='Valuation', order=sortOrder)
    for stock in stock_list:
      equity = Equity(stock['Ticker'])
      equity.equityType = 'stock'
      portfolio.append(equity)
  except:
    pass
  return portfolio

def getStocksSymbols(cap,sortOrder='-epsyoy1'):
  symbolList = []
  try:
    stock_list = Screener(filters=cap, table='Valuation', order=sortOrder)
    for stock in stock_list:
      symbolList.append(stock['Ticker'])
  except:
    pass
  return symbolList

