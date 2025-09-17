# app.py
import azure.functions as func

# Create a single shared FunctionApp instance
app = func.FunctionApp()

# Import routes so their decorators attach to `app`
# (imports must come AFTER app creation)
from routes import health, rent_prefetch, rent_analyze  # noqa: E402,F401