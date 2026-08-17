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
def get_pillar_jobs():
    try:
        # 1. GLOBAL UNEMPLOYMENT
        us_u = get_fred_data("UNRATE", limit=60)
        uk_u = get_fred_data("LRHUTTTTGBM156S", limit=60)
        eu_u = get_fred_data("LRHUTTTTDEM156S", limit=60) 
        
        # 2. US LABOR TIGHTNESS
        jolts = get_fred_data("JTSJOL", limit=24) 
        nfp = get_fred_data("PAYEMS", limit=24, units="chg") 
        
        # 3. WAGE INFLATION (New Metric: 5 Years YoY %)
        wages = get_fred_data("CES0500000003", limit=60, units="pc1")
        
        return {
            "US_Unemp": us_u,
            "UK_Unemp": uk_u,
            "EU_Unemp": eu_u,
            "US_JOLTS": jolts,
            "US_NFP": nfp,
            "US_Wages": wages # <-- Make sure to add this to the payload!
        }
    except Exception as e:
        print(f"Error in pillar-jobs: {e}")
        return {}

@app.get("/api/pillar-rates")
def get_pillar_rates():
    try:
        # 1. CENTRAL BANK RATES (Strict 60-Month Alignment)
        fed = get_fred_data("FEDFUNDS", limit=60)
        
        # PRO-TRICK: ECBDFR is a Daily series. We inject '&frequency=m' into 
        # the 'units' parameter to force the FRED API to convert it to Monthly averages!
        ecb = get_fred_data("ECBDFR", limit=60, units="lin&frequency=m")
        
        # 2. GLOBAL SOVEREIGN SPREADS (Strict 60-Month Alignment)
        # CRITICAL FIX: Swapped 'DGS10' (Daily) to 'GS10' (Monthly)
        us_10y = get_fred_data("GS10", limit=60) 
        uk_10y = get_fred_data("IRLTLT01GBM156N", limit=60)
        ger_10y = get_fred_data("IRLTLT01DEM156N", limit=60)
        
        return {
            "Fed_Funds": fed,
            "ECB_Rate": ecb,
            "US_10Y": us_10y,
            "UK_10Y": uk_10y,
            "GER_10Y": ger_10y
        }
    except Exception as e:
        print(f"Error in pillar-rates: {e}")
        return {}

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
    """Builds the dynamic timeline with Global Macro Data + International Mega-Cap Earnings"""
    import yfinance as yf
    from datetime import datetime, timedelta
    import requests
    import os

    today = datetime.now()
    start_date = (today - timedelta(days=60)).strftime('%Y-%m-%d')
    end_date = (today + timedelta(days=60)).strftime('%Y-%m-%d')
    
    # Expanded FRED Releases: 
    # US (10=CPI, 50=NFP, 53=GDP, 13=Ind Prod, 9=Retail, 46=PPI)
    # Global (322=ECB Rate, 295=BOE Rate, 254=EU HICP, 356=UK CPI, 172=China GDP)
    target_releases = [10, 50, 53, 13, 9, 46, 322, 295, 254, 356, 172]
    past, future = [], []
    today_str = today.strftime('%Y-%m-%d')
    
    # 1. FETCH GLOBAL MACRO DATA
    try:
        FRED_API_KEY = os.getenv("FRED_API_KEY")
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})
        
        for rid in target_releases:
            url = f"https://api.stlouisfed.org/fred/release/dates?release_id={rid}&api_key={FRED_API_KEY}&file_type=json&include_release_dates_with_no_data=true&limit=1000"
            res = session.get(url, timeout=5)
            
            if res.status_code == 200:
                dates = res.json().get("release_dates", [])
                for d in dates:
                    date_str = d.get("date")
                    if start_date <= date_str <= end_date:
                        event = {"release_id": rid, "date": date_str}
                        if date_str < today_str:
                            past.append(event)
                        elif date_str >= today_str:
                            future.append(event)
    except Exception as e:
        print(f"FRED fetch failed: {e}")

    # 2. FETCH GLOBAL MEGA-CAP EARNINGS (US + Top International ADRs)
    mega_caps = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "LLY", "AVGO", "JPM", "TSM", "MU", "SPCX", "CRM", "NFLX"]
    
    for ticker in mega_caps:
        try:
            stock = yf.Ticker(ticker)
            cal = stock.calendar
            
            if isinstance(cal, dict) and 'Earnings Date' in cal:
                raw_earnings = cal['Earnings Date']
                if isinstance(raw_earnings, list) and len(raw_earnings) > 0:
                    earn_date = raw_earnings[0].strftime('%Y-%m-%d')
                    
                    if start_date <= earn_date <= end_date:
                        event = {"release_id": "EARNINGS", "date": earn_date, "ticker": ticker}
                        if earn_date < today_str:
                            past.append(event)
                        else:
                            future.append(event)
        except Exception:
            pass 
                            
    # 3. SORT & SLICE HYBRID ARRAYS
    # We are increasing the slice to 8 events per side to accommodate the denser global calendar
    past = sorted(past, key=lambda x: x["date"])
    future = sorted(future, key=lambda x: x["date"])
    
    return {"past": past[-8:], "future": future[:8]}
