# app.py
import azure.functions as func
app = func.FunctionApp()

from routes import health, rent_prefetch, rent_analyze, tax_estimate  # <-- add tax_estimate