# app.py (at repo root, next to host.json)
import azure.functions as func

# Create the Function App instance
app = func.FunctionApp()

# 🔴 IMPORTANT: import modules that register routes via decorators
# These imports must succeed at import-time (no try/except swallowing errors)
from routes import rent_prefetch
from routes import rent_analyze          # if you have it
from routes import portfolio_rank
from routes import health                # optional simple /health route