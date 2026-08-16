from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv, find_dotenv

# Aggressively load the secure vault
load_dotenv(find_dotenv())
FRED_API_KEY = os.getenv("FRED_API_KEY")

app = FastAPI(title="SethiMacro Global Engine")

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
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json&limit={limit}&sort_order=desc&units={units}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return [
                {"date": obs["date"], "value": float(obs["value"])} 
                for obs in data["observations"] 
                if obs["value"] != "."
            ]
    except Exception as e:
        print(f"Failed to fetch {series_id}: {e}")
    return []

# ==========================================
# --- GLOBAL MACRO PILLARS ---
# ==========================================

@app.get("/")
def read_root():
    return {"status": "SethiMacro Global Quant Engine Online"}

@app.get("/api/pillar-jobs")
def get_jobs_data():
    return {
        "US_NFP": get_fred_data("PAYEMS", limit=24, units="ch1"),
        "US_JOLTS": get_fred_data("JTSJOL", limit=24),
        "US_Unemp": get_fred_data("UNRATE", limit=12),
        "UK_Unemp": get_fred_data("LRHUTTTTGBA156N", limit=5), # Annual representation
        "EU_Unemp": get_fred_data("LRUN64TTEZA156S", limit=5)  # Annual representation
    }

@app.get("/api/pillar-rates")
def get_rates_data():
    return {
        "US_CPI": get_fred_data("CPIAUCSL", limit=12, units="pc1"),
        "US_Core_PCE": get_fred_data("PCEPILFE", limit=12, units="pc1"),
        "US_PPI": get_fred_data("PPIACO", limit=12, units="pc1"),
        "UK_CPI": get_fred_data("CPALTT01GBM657N", limit=12), 
        "Fed_Funds": get_fred_data("FEDFUNDS", limit=24),
        "ECB_Rate": get_fred_data("ECBDFR", limit=24),
        "US_10Y": get_fred_data("DGS10", limit=30),
        "UK_10Y": get_fred_data("IRLTLT01GBM156N", limit=30),
        "GER_10Y": get_fred_data("IRLTLT01DEM156N", limit=30)
    }

@app.get("/api/pillar-gdp")
def get_gdp_data():
    return {
        "US_GDP": get_fred_data("GDPC1", limit=12, units="pc1"),
        "US_Ind_Prod": get_fred_data("INDPRO", limit=12, units="pc1")
    }

@app.get("/api/pillar-fx")
def get_fx_data():
    # Pulling 250 days of data for rich YTD currency charts
    return {
        "DXY": get_fred_data("DTWEXBGS", limit=250),
        "GBP_USD": get_fred_data("DEXUSUK", limit=250),
        "EUR_USD": get_fred_data("DEXUSEU", limit=250),
        "USD_CNY": get_fred_data("DEXCHUS", limit=250)
    }

@app.get("/api/quant-signals")
def get_quant_signals():
    signals = {}
    
    # 1. Yield Spread
    try:
        y10 = get_fred_data("DGS10", limit=1)[0]["value"]
        y2 = get_fred_data("DGS2", limit=1)[0]["value"]
        spread = round(y10 - y2, 2)
        
        uk10 = get_fred_data("IRLTLT01GBM156N", limit=1)
        uk10_val = round(uk10[0]["value"], 2) if uk10 else "N/A"
        
        signals["Yield_Spread"] = {"us_spread": spread, "status": "INVERTED" if spread < 0 else "NORMAL", "us_10y": y10, "uk_10y": uk10_val}
    except Exception:
        signals["Yield_Spread"] = {"us_spread": "N/A", "status": "Error"}

    # 2. Sahm Rule
    try:
        unrate = get_fred_data("UNRATE", limit=15)
        if len(unrate) >= 12:
            rates = [x["value"] for x in unrate][::-1]
            three_mo_avgs = [sum(rates[i:i+3]) / 3 for i in range(len(rates) - 2)]
            sahm_value = round(three_mo_avgs[-1] - (min(three_mo_avgs[-12:-1]) if len(three_mo_avgs) > 1 else min(three_mo_avgs[:-1])), 2)
            signals["Sahm_Rule"] = {"value": sahm_value, "status": "RECESSION TRIGGERED" if sahm_value >= 0.50 else "NORMAL"}
        else:
            signals["Sahm_Rule"] = {"value": "N/A", "status": "Awaiting Data"}
    except Exception:
        signals["Sahm_Rule"] = {"value": "N/A", "status": "Error"}

    # 3. Taylor Rule
    try:
        core_pce = get_fred_data("PCEPILFE", limit=1, units="pc1")[0]["value"]
        unemp = get_fred_data("UNRATE", limit=1)[0]["value"]
        actual_fed_funds = get_fred_data("FEDFUNDS", limit=1)[0]["value"]
        
        target_rate = round(core_pce + 2.0 + (0.5 * (core_pce - 2.0)) - (1.0 * (unemp - 4.0)), 2)
        gap = round(actual_fed_funds - target_rate, 2)
        bias = f"Restrictive (+{gap}%)" if gap > 0.50 else (f"Accommodative ({gap}%)" if gap < -0.50 else "Neutral")
        
        signals["Taylor_Rule"] = {"prescribed_rate": target_rate, "actual_rate": actual_fed_funds, "policy_bias": bias}
    except Exception:
         signals["Taylor_Rule"] = {"value": "N/A", "status": "Error"}
         
    # 4. DXY Momentum (FIXED)
    try:
        dxy = get_fred_data("DTWEXBGS", limit=25) # Approx 1 month of trading days
        if len(dxy) > 5:
            current = dxy[0]["value"]
            past = dxy[-1]["value"] # Safely grab the oldest available data point in our array
            pct_change = round(((current - past)/past)*100, 2)
            signals["DXY_Strength"] = {"value": round(current, 2), "status": f"+{pct_change}% (30D)" if pct_change >= 0 else f"{pct_change}% (30D)"}
        else:
            signals["DXY_Strength"] = {"value": "N/A", "status": "Awaiting Data"}
    except Exception:
        signals["DXY_Strength"] = {"value": "N/A", "status": "Error"}
         
    return signals

@app.get("/api/calendar-timeline")
def get_macro_timeline():
    """Builds the dynamic 60-day timeline"""
    today = datetime.now()
    start_date = (today - timedelta(days=30)).strftime('%Y-%m-%d')
    end_date = (today + timedelta(days=30)).strftime('%Y-%m-%d')
    
    # FIX 1: Use 'early_date' and 'late_date' to grab future schedules, not vintage history
    url = f"https://api.stlouisfed.org/fred/releases/dates?api_key={FRED_API_KEY}&file_type=json&early_date={start_date}&late_date={end_date}&limit=300"
    
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            dates = res.json().get("release_dates", [])
            major_releases = [d for d in dates if d.get("release_id") in [10, 50, 46, 21, 9, 18]]
            
            past, future = [], []
            today_str = today.strftime('%Y-%m-%d')
            
            for event in major_releases:
                if event.get("date") < today_str: 
                    past.append(event)
                else: 
                    future.append(event)
                    
            # FIX 2: Force strict chronological sorting (oldest to newest)
            past = sorted(past, key=lambda x: x["date"])
            future = sorted(future, key=lambda x: x["date"])
            
            return {"past": past[-5:], "future": future[:5]} 
    except Exception as e:
        print(f"Timeline fetch failed: {e}")
    return {"past": [], "future": []}
