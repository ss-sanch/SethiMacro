from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from datetime import datetime
from dotenv import load_dotenv, find_dotenv

# Aggressively load the secure vault
load_dotenv(find_dotenv())
FRED_API_KEY = os.getenv("FRED_API_KEY")

app = FastAPI(title="SethiMacro Data Engine")

# Allow the frontend to talk to the backend without security blocks
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# --- CORE DATA FETCHING ENGINE ---
# ==========================================

def get_fred_data(series_id, limit=12, units="lin"):
    """
    Helper function to ping the FRED API.
    'units=lin' returns raw numbers (like interest rates).
    'units=pc1' returns Year-over-Year percent change (perfect for Inflation).
    'units=ch1' returns 1-month absolute change (perfect for Job additions).
    """
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json&limit={limit}&sort_order=desc&units={units}"
    
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            # Clean the data: extract just the date and value, and ignore empty "." values
            return [
                {"date": obs["date"], "value": float(obs["value"])} 
                for obs in data["observations"] 
                if obs["value"] != "."
            ]
    except Exception as e:
        print(f"Failed to fetch {series_id}: {e}")
    return []

# ==========================================
# --- DASHBOARD API ROUTES ---
# ==========================================

@app.get("/")
def read_root():
    return {"status": "SethiMacro Quant Engine Online"}

@app.get("/api/yield-curve")
def get_yield_curve():
    # Expanded to include the 5-Year Treasury for a smoother curve
    try:
        return {
            "3_Month": get_fred_data("DGS3MO", limit=1)[0],
            "2_Year": get_fred_data("DGS2", limit=1)[0],
            "5_Year": get_fred_data("DGS5", limit=1)[0],
            "10_Year": get_fred_data("DGS10", limit=1)[0],
            "30_Year": get_fred_data("DGS30", limit=1)[0]
        }
    except Exception as e:
        return {"status": "Error", "message": str(e)}

@app.get("/api/macro-metrics")
def get_macro_metrics():
    # The ultimate institutional data payload
    try:
        return {
            "CPI_YoY": get_fred_data("CPIAUCSL", limit=12, units="pc1"),
            "Core_PCE_YoY": get_fred_data("PCEPILFE", limit=12, units="pc1"),
            "PPI_Wholesale_YoY": get_fred_data("PPIACO", limit=12, units="pc1"),
            "Fed_Funds_Rate": get_fred_data("FEDFUNDS", limit=12),
            "Unemployment_Rate": get_fred_data("UNRATE", limit=12),
            "Nonfarm_Payrolls_MoM": get_fred_data("PAYEMS", limit=12, units="ch1"),
            "Jobless_Claims": get_fred_data("ICSA", limit=12),
            "High_Yield_Spread": get_fred_data("BAMLH0A0HYM2", limit=12),
            "Real_10Y_Yield": get_fred_data("DFII10", limit=12),
            "Breakeven_10Y": get_fred_data("T10YIE", limit=12)
        }
    except Exception as e:
        return {"status": "Error", "message": str(e)}

@app.get("/api/quant-signals")
def get_quant_signals():
    """
    Proprietary Quant Engine: Synthesizes raw data into actionable mathematical signals.
    """
    signals = {}
    
    # 1. 2Y/10Y Yield Spread Inversion Alert
    try:
        y10 = get_fred_data("DGS10", limit=1)[0]["value"]
        y2 = get_fred_data("DGS2", limit=1)[0]["value"]
        spread = round(y10 - y2, 2)
        signals["Yield_Spread_2Y10Y"] = {
            "value": spread,
            "status": "INVERTED (Recession Warning)" if spread < 0 else "NORMAL"
        }
    except Exception:
        signals["Yield_Spread_2Y10Y"] = {"value": "N/A", "status": "Error"}

    # 2. The Sahm Rule Recession Indicator
    # Math: Current 3-mo avg unemployment minus the lowest 3-mo avg over the last 12 months.
    try:
        unrate = get_fred_data("UNRATE", limit=15) # Get 15 months to calculate moving averages
        if len(unrate) == 15:
            rates = [x["value"] for x in unrate][::-1] # Reverse to chronological order (oldest to newest)
            
            # Calculate 3-month moving averages
            three_mo_avgs = []
            for i in range(len(rates) - 2):
                three_mo_avgs.append(sum(rates[i:i+3]) / 3)
            
            current_3mo_avg = three_mo_avgs[-1]
            lowest_12mo_avg = min(three_mo_avgs[:-1]) # Lowest of the preceding periods
            
            sahm_value = round(current_3mo_avg - lowest_12mo_avg, 2)
            signals["Sahm_Rule"] = {
                "value": sahm_value,
                "status": "RECESSION TRIGGERED" if sahm_value >= 0.50 else "NORMAL"
            }
    except Exception:
        signals["Sahm_Rule"] = {"value": "N/A", "status": "Error"}

    # 3. The Taylor Rule Rate Gap Model
    # Math: Target Rate = Neutral Rate (2%) + Core PCE + 0.5*(Core PCE - 2%) - 1.0*(Unemployment - Natural Unemployment(4%))
    try:
        core_pce = get_fred_data("PCEPILFE", limit=1, units="pc1")[0]["value"]
        unemp = get_fred_data("UNRATE", limit=1)[0]["value"]
        actual_fed_funds = get_fred_data("FEDFUNDS", limit=1)[0]["value"]
        
        target_rate = core_pce + 2.0 + (0.5 * (core_pce - 2.0)) - (1.0 * (unemp - 4.0))
        target_rate = round(target_rate, 2)
        gap = round(actual_fed_funds - target_rate, 2)
        
        if gap > 0.50: bias = f"Restrictive (+{gap}%)"
        elif gap < -0.50: bias = f"Accommodative ({gap}%)"
        else: bias = "Neutral"
        
        signals["Taylor_Rule"] = {
            "prescribed_rate": target_rate,
            "actual_rate": actual_fed_funds,
            "policy_bias": bias
        }
    except Exception:
         signals["Taylor_Rule"] = {"value": "N/A", "status": "Error"}
         
    return signals

@app.get("/api/calendar")
def get_macro_calendar():
    """Fetches upcoming major economic release dates."""
    today = datetime.now().strftime('%Y-%m-%d')
    url = f"https://api.stlouisfed.org/fred/releases/dates?api_key={FRED_API_KEY}&file_type=json&realtime_start={today}&limit=50"
    
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            dates = res.json().get("release_dates", [])
            # Filter for specific major releases to keep the dashboard clean
            major_releases = [d for d in dates if d.get("release_id") in [10, 50, 46, 21]] # 10=CPI, 50=Employment, 46=GDP, 21=Industrial Prod
            return major_releases[:5] # Return next 5 major catalysts
    except Exception as e:
        print(f"Calendar fetch failed: {e}")
    return []