from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse # <-- ADD THIS
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from dotenv import load_dotenv, find_dotenv

# Aggressively load the secure vault
load_dotenv(find_dotenv())
FRED_API_KEY = os.getenv("FRED_API_KEY")

app = FastAPI()

# Allow the frontend to talk to the backend without security blocks
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CORE DATA FETCHING ENGINE ---
def get_fred_data(series_id, limit=12, units="lin"):
    """
    Helper function to ping the FRED API.
    'units=lin' returns raw numbers (like interest rates).
    'units=pc1' returns Year-over-Year percent change (perfect for Inflation).
    """
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json&limit={limit}&sort_order=desc&units={units}"
    
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        # Clean the data: extract just the date and value, and ignore empty "." values
        clean_data = [
            {"date": obs["date"], "value": float(obs["value"])} 
            for obs in data["observations"] 
            if obs["value"] != "."
        ]
        return clean_data
    else:
        raise HTTPException(status_code=400, detail=f"Failed to fetch {series_id} from FRED")

# --- DASHBOARD API ROUTES ---

@app.get("/")
def read_root():
    # Serve the frontend dashboard when someone visits the main URL
    return FileResponse("index.html")

@app.get("/api/yield-curve")
def get_yield_curve():
    # Fetch just the single latest value for each maturity to plot the live curve
    try:
        return {
            "3_Month": get_fred_data("DGS3MO", limit=1)[0],
            "2_Year": get_fred_data("DGS2", limit=1)[0],
            "10_Year": get_fred_data("DGS10", limit=1)[0],
            "30_Year": get_fred_data("DGS30", limit=1)[0]
        }
    except Exception as e:
        return {"status": "Error", "message": str(e)}

@app.get("/api/macro-metrics")
def get_macro_metrics():
    # Fetch the last 12 data points (months/weeks) for broad economic tracking
    try:
        return {
            # units="pc1" forces the Fed to calculate Year-over-Year Inflation for us!
            "CPI_Inflation_YoY": get_fred_data("CPIAUCSL", limit=12, units="pc1"),
            "Fed_Funds_Rate": get_fred_data("FEDFUNDS", limit=12)
        }
    except Exception as e:
        return {"status": "Error", "message": str(e)}