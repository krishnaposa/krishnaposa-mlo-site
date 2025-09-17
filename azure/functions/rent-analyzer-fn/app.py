import azure.functions as func
app = func.FunctionApp()

from routes import health, rent_prefetch, rent_analyze, expense_all  # add expense_all