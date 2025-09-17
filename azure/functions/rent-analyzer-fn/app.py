# function_app.py  (must be at the Function App root, next to host.json)
import azure.functions as func

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Import modules that declare routes with @app.function_name
from routes import health
from routes import rent_prefetch
from routes import rent_analyze        # if you have it
from routes import portfolio_rank