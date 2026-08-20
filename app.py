from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv, find_dotenv
import time

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

def get_fred_data_cached(series_id, limit=12, units="lin"):
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
# THE ENTERPRISE RAM CACHE ENGINE
# ==========================================
MACRO_CACHE = {}
CACHE_EXPIRE_SECONDS = 43200 # 12 Hours (FRED only updates data daily/monthly anyway)

def get_fred_data_cached_cached(series_id, limit=60, units="lin"):
    """
    Checks the RAM cache first. If the data is missing or older than 12 hours,
    it fetches fresh data from FRED and saves it to RAM.
    """
    cache_key = f"{series_id}_{limit}_{units}"
    current_time = time.time()
    
    # 1. If we have the data and it's fresh, return it instantly (0.001 seconds)
    if cache_key in MACRO_CACHE:
        cached_time, cached_data = MACRO_CACHE[cache_key]
        if current_time - cached_time < CACHE_EXPIRE_SECONDS:
            return cached_data
            
    # 2. If it's missing or old, fetch it from FRED (1-2 seconds)
    print(f"Cache miss or expired for {series_id}. Fetching fresh data...")
    fresh_data = get_fred_data(series_id, limit=limit, units=units)
    
    # 3. Save to RAM and return
    if fresh_data: # Only cache if the fetch was successful
        MACRO_CACHE[cache_key] = (current_time, fresh_data)
        
    return fresh_data
# ==========================================
# --- GLOBAL MACRO PILLARS ---
# ==========================================

@app.get("/")
def read_root():
    return {"status": "SethiMacro Global Quant Engine Online"}

@app.get("/api/pillar-jobs")
def get_pillar_jobs():
    try:
        # 1. GLOBAL UNEMPLOYMENT (Force 60 months / 5 Years)
        us_u = get_fred_data_cached("UNRATE", limit=60)
        uk_u = get_fred_data_cached("LRHUTTTTGBM156S", limit=60)
        eu_u = get_fred_data_cached("LRHUTTTTDEM156S", limit=60) 
        
        # 2. US LABOR TIGHTNESS
        jolts = get_fred_data_cached("JTSJOL", limit=24) 
        # Note: NFP MUST have units="chg" to show monthly additions
        nfp = get_fred_data_cached("PAYEMS", limit=24, units="chg") 
        
        # 3. WAGE INFLATION 
        # Note: Wages MUST have units="pc1" to show YoY %
        wages = get_fred_data_cached("CES0500000003", limit=60, units="pc1")
        
        # CRITICAL FIX: These keys must perfectly match the JavaScript frontend
        return {
            "US_Unemp": us_u,
            "UK_Unemp": uk_u,
            "EU_Unemp": eu_u,
            "US_JOLTS": jolts,
            "US_NFP": nfp,
            "US_Wages": wages
        }
    except Exception as e:
        print(f"Error in pillar-jobs: {e}")
        return {}

@app.get("/api/pillar-rates")
def get_pillar_rates():
    try:
        # 1. CENTRAL BANK RATES (Synced to Monthly)
        fed = get_fred_data_cached("FEDFUNDS", limit=60)
        ecb = get_fred_data_cached("ECBDFR", limit=60, units="lin&frequency=m")
        
        # 2. SOVEREIGN SPREADS
        us_10y = get_fred_data_cached("GS10", limit=60) 
        uk_10y = get_fred_data_cached("IRLTLT01GBM156N", limit=60)
        ger_10y = get_fred_data_cached("IRLTLT01DEM156N", limit=60)

        # 3. ADVANCED INFLATION TRACKER (The Restored Graph)
        cpi = get_fred_data_cached("CPIAUCSL", limit=60, units="pc1") # pc1 = YoY %
        pce = get_fred_data_cached("PCEPILFE", limit=60, units="pc1")
        ppi = get_fred_data_cached("WPSFD4131", limit=60, units="pc1")

        # 4. REAL COST OF CAPITAL (The New Pro Quant Chart)
        breakeven = get_fred_data_cached("T10YIE", limit=60, units="lin&frequency=m") # Inflation Expectations
        real_yield = get_fred_data_cached("DFII10", limit=60, units="lin&frequency=m") # TIPS Real Yield
        
        return {
            "Fed_Funds": fed, "ECB_Rate": ecb,
            "US_10Y": us_10y, "UK_10Y": uk_10y, "GER_10Y": ger_10y,
            "CPI": cpi, "PCE": pce, "PPI": ppi,
            "Breakeven": breakeven, "Real_Yield": real_yield
        }
    except Exception as e:
        print(f"Error in pillar-rates: {e}")
        return {}

@app.get("/api/pillar-gdp")
def get_pillar_gdp():
    try:
        # 1. GLOBAL REAL GDP (Harmonized YoY % Growth, 20 Quarters / 5 Years)
        us_gdp = get_fred_data_cached("GDPC1", limit=20, units="pc1") 
        
        # CRITICAL FIX: Swapped to the official UK ONS Real GDP (Chained Volume) ticker
        uk_gdp = get_fred_data_cached("UKNQGSP", limit=20, units="pc1") 
        
        eu_gdp = get_fred_data_cached("CLVMEURSCAB1GQEA19", limit=20, units="pc1") 
        
        # 2. US INDUSTRIAL PRODUCTION (YoY %)
        indpro = get_fred_data_cached("INDPRO", limit=60, units="pc1") 
        
        # 3. US RETAIL SALES (YoY %)
        retail = get_fred_data_cached("RSAFS", limit=60, units="pc1")
        
        # 4. CONSUMER SENTIMENT (Index Level)
        sentiment = get_fred_data_cached("UMCSENT", limit=60)
        
        return {
            "US_GDP": us_gdp,
            "UK_GDP": uk_gdp,
            "EU_GDP": eu_gdp,
            "IndPro": indpro,
            "Retail_Sales": retail,
            "Sentiment": sentiment
        }
    except Exception as e:
        print(f"Error in pillar-gdp: {e}")
        return {}

@app.get("/api/pillar-fx")
def get_fx_data():
    # Pulling 250 days of data for rich YTD currency charts
    return {
        "DXY": get_fred_data_cached("DTWEXBGS", limit=250),
        "GBP_USD": get_fred_data_cached("DEXUSUK", limit=250),
        "EUR_USD": get_fred_data_cached("DEXUSEU", limit=250),
        "USD_CNY": get_fred_data_cached("DEXCHUS", limit=250)
    }

@app.get("/api/quant-signals")
def get_quant_signals():
    signals = {}
    
    # 1. Yield Spread
    try:
        y10 = get_fred_data_cached("DGS10", limit=1)[0]["value"]
        y2 = get_fred_data_cached("DGS2", limit=1)[0]["value"]
        spread = round(y10 - y2, 2)
        
        uk10 = get_fred_data_cached("IRLTLT01GBM156N", limit=1)
        uk10_val = round(uk10[0]["value"], 2) if uk10 else "N/A"
        
        signals["Yield_Spread"] = {"us_spread": spread, "status": "INVERTED" if spread < 0 else "NORMAL", "us_10y": y10, "uk_10y": uk10_val}
    except Exception:
        signals["Yield_Spread"] = {"us_spread": "N/A", "status": "Error"}

    # 2. Sahm Rule
    try:
        unrate = get_fred_data_cached("UNRATE", limit=15)
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
        core_pce = get_fred_data_cached("PCEPILFE", limit=1, units="pc1")[0]["value"]
        unemp = get_fred_data_cached("UNRATE", limit=1)[0]["value"]
        actual_fed_funds = get_fred_data_cached("FEDFUNDS", limit=1)[0]["value"]
        
        target_rate = round(core_pce + 2.0 + (0.5 * (core_pce - 2.0)) - (1.0 * (unemp - 4.0)), 2)
        gap = round(actual_fed_funds - target_rate, 2)
        bias = f"Restrictive (+{gap}%)" if gap > 0.50 else (f"Accommodative ({gap}%)" if gap < -0.50 else "Neutral")
        
        signals["Taylor_Rule"] = {"prescribed_rate": target_rate, "actual_rate": actual_fed_funds, "policy_bias": bias}
    except Exception:
         signals["Taylor_Rule"] = {"value": "N/A", "status": "Error"}
         
    # 4. DXY Momentum (FIXED)
    try:
        dxy = get_fred_data_cached("DTWEXBGS", limit=25) # Approx 1 month of trading days
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
