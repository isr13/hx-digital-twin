import datetime
import numpy as np
import pandas as pd
from fastapi import FastAPI, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from scipy.stats import linregress
import uvicorn
import io
import os

app = FastAPI(title="PHE Digital Twin Core Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- GLOBAL CONSTANTS ---
SURFACE_AREA = 66.3
FOULING_LIMIT = 0.00045
DATA_FILE_PATH = "hx_data.xlsx"

# Global dataframe state
df_clean = pd.DataFrame()

def get_10pc_koh_density(t_celsius):
    return 1098 - (0.41 * t_celsius) - (0.0016 * (t_celsius ** 2))

def get_10pc_koh_cp(t_celsius):
    return 3730 + (1.2 * t_celsius) - (0.002 * (t_celsius ** 2))

def estimate_cooling_flow(valve_opening_pct):
    X = valve_opening_pct / 100.0
    if X <= 0.03: return 0.0
    # Increase Kv_max to match physical realities of a 66.3 m2 heat exchanger
    Kv_max = 1200.0
    R = 50.0
    delta_p_valve = 1.5
    Kv_actual = Kv_max * (R ** (X - 1.0))
    vol_flow_m3h = Kv_actual * np.sqrt(delta_p_valve)
    return (vol_flow_m3h * 985.0) / 3600.0

def calculate_u_clean_dynamic(m_hot, m_cold):
    # This function is now only used as a fallback if init is not done
    U_DESIGN = 6988.0
    M_HOT_DESIGN = 128500.0 / 3600.0
    M_COLD_DESIGN = 97390.0 / 3600.0
    if m_hot <= 0 or m_cold <= 0: return U_DESIGN
    return U_DESIGN * ((m_hot / M_HOT_DESIGN) ** 0.65) * ((m_cold / M_COLD_DESIGN) ** 0.4)

# Global constant for the baseline U_clean
BASELINE_U_CLEAN = None

def process_dataframe(df):
    global BASELINE_U_CLEAN
    """Core logic to transform raw data into a digital twin metrics dataframe"""
    # Normalize timestamp key
    if 'timestamp' in df.columns:
        df['Timestamp'] = pd.to_datetime(df['timestamp'])
    elif 'Timestamp' in df.columns:
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
    else:
        df['Timestamp'] = pd.to_datetime(range(len(df)), unit='m', origin='2026-01-01')

    # Map industrial tags to logical engine parameters
    rename_map = {
        'T_PR_out': 'T_hot_out',
        'V_CW_pos': 'Valve_position',
        'P_PR_in': 'P_hot_in',
        'F_PR_out': 'Flow_hot_out'
    }
    df = df.rename(columns=rename_map)

    # Ensure all required columns exist
    required = ['T_hot_out', 'Valve_position', 'P_hot_in', 'Flow_hot_out']
    for col in required:
        if col not in df.columns:
            df[col] = 0.0

    # Synthesize thermodynamic inputs if missing
    days = (df['Timestamp'] - df['Timestamp'].min()).dt.total_seconds() / (24 * 3600)
    total_days = max(1.0, days.max())
    t_norm = days / total_days
    
    np.random.seed(42)
    if 'T_hot_in' not in df.columns:
        df['T_hot_in'] = 85.0 + 2.0 * np.sin(2 * np.pi * t_norm * 365) + np.random.normal(0, 0.2, len(df))
    if 'T_cold_in' not in df.columns:
        df['T_cold_in'] = 15.0 + 8.0 * np.sin(2 * np.pi * t_norm * 1) + np.random.normal(0, 0.2, len(df))

    # Calculate Fouling Factor (Rf)
    rf_list = []
    u_clean_list = []
    for i, row in df.iterrows():
        avg_t_hot = (row['T_hot_in'] + row['T_hot_out']) / 2
        m_hot = (row['Flow_hot_out'] * get_10pc_koh_density(avg_t_hot)) / 3600.0
        Q = m_hot * get_10pc_koh_cp(avg_t_hot) * (row['T_hot_in'] - row['T_hot_out'])
        m_cold = estimate_cooling_flow(row['Valve_position'])
        
        if m_cold <= 0:
            rf_list.append(rf_list[-1] if rf_list else 0.0)
            continue
            
        t_cold_out = row['T_cold_in'] + (Q / (m_cold * 4184.0))
        dT1, dT2 = row['T_hot_in'] - t_cold_out, row['T_hot_out'] - row['T_cold_in']
        
        if dT1 <= 0 or dT2 <= 0 or np.isclose(dT1, dT2):
            rf_list.append(rf_list[-1] if rf_list else 0.0)
            continue
            
        lmtd = (dT1 - dT2) / np.log(dT1 / dT2)
        u_act = Q / (SURFACE_AREA * lmtd)
        # Determine baseline U_clean during first 50 steps
        if i < 50:
            u_clean_list.append(u_act)
            if i == 49:
                BASELINE_U_CLEAN = np.mean(u_clean_list)
            rf_list.append(0.0) # Assume clean at start
        else:
            # Use constant baseline U_clean for the rest
            u_cln = BASELINE_U_CLEAN if BASELINE_U_CLEAN else calculate_u_clean_dynamic(m_hot, m_cold)
            rf_now= max(0.0, (1/u_act) - (1/u_cln))
            rf_list.append(rf_now)

    df['Fouling_Factor'] = rf_list
    df['Fouling_Factor_Smooth'] = df['Fouling_Factor'].rolling(window=24, min_periods=1).mean()
    return df

def init_dataset():
    global df_clean
    try:
        if os.path.exists(DATA_FILE_PATH):
            df = pd.read_excel(DATA_FILE_PATH)
            df_clean = process_dataframe(df)
        else:
            raise FileNotFoundError
    except Exception as e:
        print(f"Initializing with mock data due to: {e}")
        intervals = 1000
        base_time = datetime.datetime(2026, 1, 1)
        timestamps = [base_time + datetime.timedelta(minutes=5*i) for i in range(intervals)]
        t = np.linspace(0, 1, intervals)
        df = pd.DataFrame({
            'timestamp': timestamps,
            'T_PR_out': np.full(intervals, 65.0) + np.random.normal(0, 0.1, intervals),
            'V_CW_pos': np.clip(35.0 + (t * 48.0), 0, 100),
            'P_PR_in': 4.2 + np.random.normal(0, 0.05, intervals),
            'F_PR_out': 115.0 + np.random.normal(0, 1.0, intervals)
        })
        df_clean = process_dataframe(df)

init_dataset()

# --- PREDICTIVE FORECASTING ---
def calculate_maintenance_date(historical_subset):
    lookback_points = min(len(historical_subset), 60 * 288)
    if lookback_points < 288:
        return "Calibrating..."
    regression_data = historical_subset.iloc[-lookback_points:]
    x_epochs = regression_data['Timestamp'].astype(np.int64) // 10**9
    y_rf = regression_data['Fouling_Factor_Smooth'].values
    slope, intercept, _, _, _ = linregress(x_epochs, y_rf)
    if slope <= 0:
        return "Stable"
    target_epoch = (FOULING_LIMIT - intercept) / slope
    if target_epoch > 2000000000:
        return "Far Horizon"
    return datetime.datetime.fromtimestamp(target_epoch).strftime('%Y-%m-%d')

# --- ENDPOINTS ---
@app.get("/api/total-steps")
def get_total_steps():
    return {"total_steps": len(df_clean)}

@app.post("/api/upload-data")
async def upload_data(file: UploadFile = File(...)):
    global df_clean
    contents = await file.read()
    if file.filename.endswith('.xlsx'):
        df = pd.read_excel(io.BytesIO(contents))
    else:
        df = pd.read_csv(io.BytesIO(contents))
    df_clean = process_dataframe(df)
    return {"status": "success", "rows": len(df_clean)}

@app.get("/api/telemetry")
def get_telemetry_step(index: int = Query(0, ge=0)):
    max_idx = len(df_clean) - 1
    safe_idx = min(index, max_idx)
    row = df_clean.iloc[safe_idx]
    historical_subset = df_clean.iloc[0:safe_idx + 1]
    
    predicted_date = calculate_maintenance_date(historical_subset)
    
    # Downsample for UI performance
    step_size = max(1, len(historical_subset) // 200)
    plot_cols = ['Timestamp', 'Fouling_Factor_Smooth', 'T_hot_in', 'T_hot_out', 'Flow_hot_out', 'P_hot_in', 'T_cold_in', 'Valve_position']
    historical_trend = historical_subset.iloc[::step_size][plot_cols].to_dict(orient="records")
    
    return {
        "metadata": {
            "timestamp": row['Timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
            "current_index": safe_idx,
            "max_index": max_idx
        },
        "telemetry": {
            "hot_flow_out": float(row['Flow_hot_out']),
            "hot_press_in": float(row['P_hot_in']),
            "hot_temp_in": float(row['T_hot_in']),
            "hot_temp_out": float(row['T_hot_out']),
            "cold_temp_in": float(row['T_cold_in']),
            "valve_position": float(row['Valve_position']),
            "fouling_factor": float(row['Fouling_Factor_Smooth']),
            "fouling_limit": FOULING_LIMIT
        },
        "forecasting": {"maintenance_date": predicted_date},
        "historical_plot": historical_trend
    }

if __name__ == "__main__":
    # Ensure any existing processes on 8000 are cleared if possible
    # Just standard run
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)


