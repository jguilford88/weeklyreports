import streamlit as st
import pandas as pd
import json
import re
import math
from datetime import datetime
import datetime as dt  # For date arithmetic

# Local timezone offset from UTC (adjust if needed / DST-aware)
LOCAL_OFFSET_HOURS = 7

# === JSON key order enforcement (from Format.json) ===
TOP_ORDER = ['project', 'survey', 'reporting_begin', 'reporting_end', 'fieldwork_begin', 'fieldwork_end', 'final_report_date', 'total', 'utilization', 'last_week_activities', 'next_week_activities']
TOTAL_ORDER = ['linear_nm', 'square_nm', 'ping_time', 'pos_time', 'acquisition_time', 'down_time']
UTIL_ORDER = ['vessel', 'date', 'linear_nm', 'square_nm', 'ping_time', 'pos_time', 'acquisition_time', 'down_time', 'down_reason', 'comment']
NUMERIC_FIELDS = ["linear_nm","square_nm","ping_time","pos_time","acquisition_time","down_time"]

from collections import OrderedDict


def order_final_json(data):
    """Return an OrderedDict of final JSON matching the template order exactly.
    Missing keys are filled with reasonable defaults ("" for text, 0 for numerics, [] for lists). Extra keys are dropped.
    """
    def _default_for_key(k):
        return 0 if k in NUMERIC_FIELDS else ""

    out = OrderedDict()
    for k in TOP_ORDER:
        if k == "total":
            total_src = data.get("total", {}) or {}
            total_ord = OrderedDict((tk, (total_src.get(tk, 0) if tk in NUMERIC_FIELDS else total_src.get(tk, ""))) for tk in TOTAL_ORDER)
            out[k] = total_ord
        elif k == "utilization":
            util_src = data.get("utilization", []) or []
            util_list = []
            for row in util_src:
                row_ord = OrderedDict()
                for uk in UTIL_ORDER:
                    val = row.get(uk, _default_for_key(uk))
                    if uk in NUMERIC_FIELDS:
                        try:
                            fv = float(val)
                            # normalize -0.0
                            val = 0 if abs(fv) == 0.0 else round(fv, 2)
                            if float(val).is_integer():
                                val = int(val)
                        except Exception:
                            val = 0
                    else:
                        val = "" if val in (None, "nan", "NaN") else str(val)
                    row_ord[uk] = val
                util_list.append(row_ord)
            out[k] = util_list
        else:
            # top-level scalar strings
            v = data.get(k, "")
            out[k] = "" if v in (None, "nan", "NaN") else v
    return out


st.set_page_config(page_title="OPR-N399-KR-25 Weekly Survey Report Generator", layout="wide")

st.title("OPR-N399-KR-25 Weekly Survey Report Generator")
st.markdown(
    "1. Upload your HIPS Line Report for the week. File must have headers and 'Line_Report' in the filename"  
    "2. Upload the POSPac log (.log) files"
    "3. Download the Productivity Excel (KR_OPR-N399-KR-25_Productivity_Report_CY25.xlsx) from Teams and drag and drop"
    "4. Review and edit the fields as needed."
)

uploaded_files = st.file_uploader(
    "Upload Line Report (.txt/.csv) and POSPac log (.log) files below.",
    type=['txt', 'csv', 'log', 'json'],
    accept_multiple_files=True
)

prod_excel_file = st.file_uploader(
    "Upload Productivity Excel (KR_OPR-N399-KR-25_Productivity_Report_CY25.xlsx)",
    type=['xlsx']
)

prod_df = None
if prod_excel_file:
    prod_df = pd.read_excel(prod_excel_file, sheet_name="Vessel Utilization Report", engine="openpyxl")
    
down_reason_lookup = {
    "Survey Equip": "Survey Equipment",
    "Mech": "Mechanical",
    "Per": "Personnel",
    "WX": "Weather",
    "Safety Stndwn": "Other"
}

# Static, not editable in UI
survey_fieldwork_begin_lookup = {
    "H14212": "07/08/2025", "H14213": "07/16/2025", "H14214": "07/23/2025", "H14215": "", "H14216": "07/31/2025",
    "H14217": "", "H14218": "", "H14219": "", "H14220": "", "H14221": "", "H14222": "", "H14223": "", "H14224": "07/08/2025"
}

vessel_lookup = {"BR": "Broughton", "SE": "Seahawk", "RI": "Brennan"}
full_vessel_map = {"BR": "OPR-N399-KR-25_BR", "SE": "OPR-N399-KR-25_SE", "RI": "OPR-N399-KR-25_RI"}
vessel_idx_map = {"Brennan": 1, "Seahawk": 2, "Broughton": 3}

def round2(val):
    try:
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return ""
        fval = float(val)
        return "" if math.isnan(fval) or fval == 0 else f"{fval:.2f}".rstrip("0").rstrip(".")
    except Exception:
        return ""

def safe_float(s):
    try:
        return float(s)
    except Exception:
        return None

def sum_blanks(vals):
    valsf = [safe_float(v) for v in vals if v not in ("", None)]
    return round2(sum(val for val in valsf if val is not None and val != 0)) if valsf else ""

def recalc_totals_from_util(util_table):
    totals = {
        "linear_nm": "",
        "square_nm": "",
        "ping_time": "",
        "pos_time": "",
        "acquisition_time": "",
        "down_time": ""
    }
    for key in totals:
        vals = [u.get(key, "") for u in util_table]
        totals[key] = sum_blanks(vals)
    return totals



def to_number_or_zero(x):
    """Return a numeric value for JSON: blanks/invalid -> 0, numbers rounded to 2 decimals.
    Integers are emitted as int (no decimal), floats keep 2-dec precision when needed.
    """
    if x in ("", None, "nan", "NaN"):
        return 0
    try:
        f = float(x)
        # Normalize -0.0 and NaNs
        if not math.isfinite(f) or abs(f) == 0.0:
            return 0
        f = round(f, 2)
        # If it's effectively an integer after rounding, cast to int
        return int(f) if float(f).is_integer() else f
    except Exception:
        return 0

def to_yyyymmdd(date_str):
    try:
        dt = pd.to_datetime(date_str)
        return dt.strftime("%Y%m%d")
    except Exception:
        return ""

def julian_day_to_mmddyyyy(jd, year):
    dt = datetime(year, 1, 1) + pd.Timedelta(days=int(jd) - 1)
    return dt.strftime("%Y/%m/%d")

def extract_pos_time_from_log(log_text):
    start = end = None
    for line in log_text.splitlines():
        if "Processing start time" in line:
            match = re.search(r"([\d\.]+)", line)
            if match:
                start = float(match.group(1))
        if "Processing end time" in line:
            match = re.search(r"([\d\.]+)", line)
            if match:
                end = float(match.group(1))
    if start is not None and end is not None and end > start:
        pos_time_hours = (end - start) / 3600.0
        return pos_time_hours
    else:
        return None

# --- Separate file types ---
line_report_df = None
pos_logs = []
previous_json = None

for file in uploaded_files or []:
    if file.name.endswith(('.txt', '.csv')) and "Line_Report" in file.name:
        file.seek(0)
        line_report_df = pd.read_csv(file)
    elif file.name.endswith('.log'):
        pos_logs.append(file)
    elif file.name.endswith('.json'):
        previous_json = json.load(file)

# --- Optional runtime template override from uploaded JSON (e.g., Format.json) ---
try:
    if isinstance(previous_json, dict) and "total" in previous_json and "utilization" in previous_json:
        # Recompute ordering lists from the uploaded JSON to guard against future template changes
        _top = list(previous_json.keys())
        _total = list(previous_json.get("total", {}).keys()) if isinstance(previous_json.get("total"), dict) else TOTAL_ORDER
        _util = list(previous_json.get("utilization", [{}])[0].keys()) if isinstance(previous_json.get("utilization"), list) and previous_json.get("utilization") else UTIL_ORDER
        if _top and _total and _util:
            TOP_ORDER[:] = _top
            TOTAL_ORDER[:] = _total
            UTIL_ORDER[:] = _util
            st.info("Using field order from uploaded JSON template.", icon="ℹ️")
except Exception as _e:
    st.warning(f"Could not apply ordering from uploaded JSON: {_e}")

default_survey = ""
default_reporting_begin = ""
default_reporting_end = ""

# --------- MIN/MAX TIME SECTION WITH UTC-7 OFFSET AND WEEK BOUNDS APPLIED ---------
if line_report_df is not None and not line_report_df.empty:
    try:
        survey_col = line_report_df.columns[0]
        first_row_survey = line_report_df[survey_col].dropna().iloc[0]
        default_survey = str(first_row_survey)
    except Exception:
        default_survey = ""
    try:
        min_time_col = [col for col in line_report_df.columns if "min time" in col.lower()][0]
        max_time_col = [col for col in line_report_df.columns if "max time" in col.lower()][0]
        min_times = pd.to_datetime(line_report_df[min_time_col], errors="coerce") - pd.Timedelta(hours=LOCAL_OFFSET_HOURS)
        max_times = pd.to_datetime(line_report_df[max_time_col], errors="coerce") - pd.Timedelta(hours=LOCAL_OFFSET_HOURS)
        min_time_val = min_times.min()
        max_time_val = max_times.max()
        # --- Set reporting week to Sunday-Saturday ---
        if pd.notnull(min_time_val):
            min_date = min_time_val.date()
            days_to_sunday = (min_date.weekday() + 1) % 7
            reporting_begin_date = min_date - dt.timedelta(days=days_to_sunday)
            default_reporting_begin = reporting_begin_date.strftime("%m/%d/%Y")
            reporting_end_date = reporting_begin_date + dt.timedelta(days=6)
            default_reporting_end = reporting_end_date.strftime("%m/%d/%Y")
        else:
            default_reporting_begin = ""
            default_reporting_end = ""
    except Exception as e:
        st.warning(f"Error extracting Reporting Begin/End from Min/Max Time: {e}")

util_table = []
if len(pos_logs) > 0 and prod_df is not None:
    n_logs = len(pos_logs)
    for idx, log_file in enumerate(pos_logs):
        log_name = log_file.name
        vessel_name = ""
        vessel_code = ""
        for code in vessel_lookup.keys():
            if f"_{code}" in log_name or f"-{code}" in log_name:
                vessel_code = code
                vessel_name = vessel_lookup[code]
                break
        if not vessel_name:
            for code in vessel_lookup.keys():
                if code in log_name:
                    vessel_name = vessel_lookup[code]
                    vessel_code = code
                    break
        dn_match = re.search(r'DN(\d{3})', log_name)
        vessel_date = ""
        if dn_match:
            julian_dn = int(dn_match.group(1))
            year_match = re.search(r'20\d{2}', log_name)
            year = int(year_match.group(0)) if year_match else (
                int(default_reporting_begin.split('/')[-1]) if default_reporting_begin else 2025
            )
            vessel_date = (datetime(year, 1, 1) + pd.Timedelta(days=int(julian_dn) - 1)).strftime("%m/%d/%Y")
        linear_nm_value = ""
        ping_time_value = ""
        if line_report_df is not None and vessel_code in full_vessel_map and vessel_date:
            vessel_col = "Vessel Name"
            min_time_col = [col for col in line_report_df.columns if "min time" in col.lower()][0]
            max_time_col = [col for col in line_report_df.columns if "max time" in col.lower()][0]
            linelength_col = [col for col in line_report_df.columns if "line length" in col.lower()][0]
            vessel_code_full = full_vessel_map[vessel_code]
            line_nm_total = 0.0
            ping_time_total = 0.0
            for i, row in line_report_df.iterrows():
                vessel_match = str(row[vessel_col]).strip() == vessel_code_full
                try:
                    min_time_val = pd.to_datetime(row[min_time_col], errors="coerce")
                    max_time_val = pd.to_datetime(row[max_time_col], errors="coerce")
                    # Apply -7 hour offset
                    if pd.notnull(min_time_val):
                        min_time_val = min_time_val - pd.Timedelta(hours=LOCAL_OFFSET_HOURS)
                    if pd.notnull(max_time_val):
                        max_time_val = max_time_val - pd.Timedelta(hours=LOCAL_OFFSET_HOURS)
                    min_time_date = min_time_val.strftime("%m/%d/%Y") if pd.notnull(min_time_val) else ""
                except Exception:
                    min_time_val, max_time_val, min_time_date = None, None, ""
                date_match = min_time_date == vessel_date
                if vessel_match and date_match:
                    try:
                        val = float(row[linelength_col])
                        line_nm_total += val
                    except:
                        pass
                    if pd.notnull(min_time_val) and pd.notnull(max_time_val):
                        diff_hours = (max_time_val - min_time_val).total_seconds() / 3600.0
                        if diff_hours > 0:
                            ping_time_total += diff_hours
            linear_nm_value = round2(line_nm_total / 1852) if line_nm_total else ""
            ping_time_value = round2(ping_time_total) if ping_time_total else ""
        log_file.seek(0)
        log_text = log_file.read().decode('utf-8', errors='ignore')
        pos_time_val = extract_pos_time_from_log(log_text)
        pos_time_value = round2(pos_time_val) if pos_time_val else ""
        v_idx = vessel_idx_map.get(vessel_name, 1)
        acq_col = f"Vessel {v_idx} Act"
        down_col = f"Vessel {v_idx} Down"
        reason_col = f"Vessel {v_idx} Reason"
        snm_val = ""
        acq_time_val = ""
        down_time_val = ""
        down_reason_val = ""
        
        survey_registry = default_survey.strip()
        # Ensure defaults in case productivity lookup yields no row
        snm_val = ""
        acq_time_val = ""
        down_time_val = ""
        down_reason_val = ""
        
        try:
            match = pd.DataFrame()
            if prod_df is not None and set(['Date','Registry Number']).issubset(set(prod_df.columns)):
                mask_date = pd.to_datetime(prod_df['Date'], errors='coerce').dt.strftime('%m/%d/%Y') == vessel_date
                mask_reg = prod_df['Registry Number'].astype(str).str.strip() == survey_registry
                match = prod_df[mask_date & mask_reg]
            if not match.empty:
                def _has_val(x):
                    try:
                        return (pd.notnull(x)) and (float(x) != 0.0)
                    except Exception:
                        return pd.notnull(x) and str(x).strip() not in ('', 'nan', 'NaN')
                preferred = match[match[acq_col].apply(_has_val)] if acq_col in match.columns else pd.DataFrame()
                row = preferred.iloc[0] if not preferred.empty else match.iloc[0]
                # Prefer the row(s) where this vessel's Act column has a real value (not NaN/blank/0)
                def _has_val(x):
                    try:
                        return (pd.notnull(x)) and (float(x) != 0.0)
                    except Exception:
                        return pd.notnull(x) and str(x).strip() not in ("", "nan", "NaN")
                preferred = match[match[acq_col].apply(_has_val)]
                row = preferred.iloc[0] if not preferred.empty else match.iloc[0]
                snm_val = round2(row.get("SNM", ""))
                acq_time_val = round2(row.get(acq_col, ""))
                down_time_val = round2(row.get(down_col, ""))
                down_reason_val = row.get(reason_col, "")
                if pd.isna(down_reason_val) or str(down_reason_val).strip().lower() == "nan":
                    down_reason_val = ""
        except Exception as e:
            st.warning(f"Productivity sheet extraction failed: {e}")
        down_reason_val_mapped = down_reason_lookup.get(str(down_reason_val).strip(), down_reason_val)
        util_table.append({
                    "vessel": vessel_name,
                    "date": vessel_date,
                    "linear_nm": linear_nm_value,
                    "ping_time": ping_time_value,
                    "pos_time": pos_time_value,
                    "square_nm": snm_val,
                    "acquisition_time": acq_time_val,
                    "down_time": down_time_val,
                    "down_reason": down_reason_val_mapped,
                    "comment": ""
        })


# --- Deduplicate by (vessel, date) and sum POS time; then sort by vessel then date ---

def _parse_mmddyyyy(s):
    try:
        return pd.to_datetime(s, format="%m/%d/%Y", errors="coerce")
    except Exception:
        return pd.NaT

grouped = {}

for u in util_table:
    key = (u.get("vessel", ""), u.get("date", ""))
    if key not in grouped:
        # Start a new aggregate entry
        base = u.copy()
        # Ensure pos_time is numeric for summation
        base["pos_time"] = safe_float(u.get("pos_time")) or 0.0
        grouped[key] = base
    else:
        # Sum POS time only (as requested)
        grouped[key]["pos_time"] = (grouped[key]["pos_time"] or 0.0) + (safe_float(u.get("pos_time")) or 0.0)
        # For other fields, keep the first non-empty value
        for k in ["linear_nm", "ping_time", "square_nm", "acquisition_time", "down_time", "down_reason", "comment"]:
            if (grouped[key].get(k) in ("", None)) and (u.get(k) not in ("", None)):
                grouped[key][k] = u[k]

# Re-apply formatting to pos_time
for v in grouped.values():
    v["pos_time"] = round2(v.get("pos_time"))

# Replace util_table with the merged list
util_table = list(grouped.values())

# Sort by vessel name, then by date (MM/DD/YYYY)
util_table.sort(key=lambda x: (x.get("vessel", ""), _parse_mmddyyyy(x.get("date", ""))))

totals_from_util = {"linear_nm": "", "square_nm": "", "ping_time": "", "pos_time": "", "acquisition_time": "", "down_time": ""}
if util_table:
    for key in totals_from_util:
        vals = [u.get(key, "") for u in util_table]
        totals_from_util[key] = sum_blanks(vals)

# ---- Editable Weekly Report (Matches Required JSON Schema) ----
st.header("Editable Weekly Report (Matches Required JSON Schema)")
with st.form("edit_json"):
    col1, col2, col3 = st.columns(3)
    with col1:
        project = st.text_input("Project", value="OPR-N399-KR-25_Columbia River, WA/OR")
        survey = st.text_input("Survey", value=default_survey, key="survey")
        reporting_begin = st.text_input("Reporting Begin (MM/DD/YYYY)", value=default_reporting_begin, key="reporting_begin")
        reporting_end = st.text_input("Reporting End (MM/DD/YYYY)", value=default_reporting_end, key="reporting_end")
    with col2:
        fieldwork_begin_default = survey_fieldwork_begin_lookup.get(survey.strip(), "")
        fieldwork_begin = st.text_input("Fieldwork Begin", value=fieldwork_begin_default)
        fieldwork_end = st.text_input("Fieldwork End", value="")
        final_report_date = st.text_input("Final Report Date", value="")
    with col3:
        last_week_activities = st.text_area("Last Week Activities", value="", height=80)
        next_week_activities = st.text_area("Next Week Activities", value="", height=80)
    st.subheader("Total (auto-summed or editable)")
    total = {}
    total["linear_nm"] = st.text_input("Total Linear NM", value=totals_from_util["linear_nm"], key="total_linear_nm")
    total["square_nm"] = st.text_input("Total Square NM", value=totals_from_util["square_nm"], key="total_square_nm")
    total["ping_time"] = st.text_input("Total Ping Time", value=totals_from_util["ping_time"], key="total_ping_time")
    total["pos_time"] = st.text_input("Total POS Time", value=totals_from_util["pos_time"], key="total_pos_time")
    total["acquisition_time"] = st.text_input("Total Acquisition Time", value=totals_from_util["acquisition_time"], key="total_acq_time")
    total["down_time"] = st.text_input("Total Down Time", value=totals_from_util["down_time"], key="total_down_time")
    submitted = st.form_submit_button("Next: Edit Vessel Utilization and Download JSON")

# ---------- Vessel Utilization Edit/Download Step ----------
if submitted and util_table:
    st.session_state.util_table = util_table
    st.session_state.header_info = {
        "project": project,
        "survey": survey,
        "reporting_begin": reporting_begin,
        "reporting_end": reporting_end,
        "fieldwork_begin": fieldwork_begin,
        "fieldwork_end": fieldwork_end,
        "final_report_date": final_report_date,
        "last_week_activities": last_week_activities,
        "next_week_activities": next_week_activities,
    }
    st.session_state.show_util_edit = True

if st.session_state.get("show_util_edit", False) and st.session_state.get("util_table"):
    st.header("Edit Vessel Utilization and Download JSON")
    # A single placeholder to render the JSON preview only once
    json_placeholder = st.empty()
    edited_table = []
    with st.form("edit_utilization_table"):
        for idx, u in enumerate(st.session_state.util_table):
            unique_prefix = f"vutil_{idx}"
            with st.expander(f"Vessel Utilization Entry #{idx+1} - {u['vessel']} {u['date']}"):
                vessel = st.text_input(f"Vessel Name", value=u["vessel"], key=f"vessel_{unique_prefix}")
                date = st.text_input(f"Date", value=u["date"], key=f"date_{unique_prefix}")
                linear_nm = st.text_input(f"Linear NM", value=u["linear_nm"], key=f"lin_{unique_prefix}")
                ping_time = st.text_input(f"Ping Time", value=u["ping_time"], key=f"ping_{unique_prefix}")
                pos_time = st.text_input(f"POS Time", value=u["pos_time"], key=f"pos_{unique_prefix}")
                square_nm = st.text_input(f"Square NM", value=u["square_nm"], key=f"sq_{unique_prefix}")
                acquisition_time = st.text_input(f"Acquisition Time", value=u["acquisition_time"], key=f"acq_{unique_prefix}")
                down_time = st.text_input(f"Down Time", value=u["down_time"], key=f"down_{unique_prefix}")
                down_reason = st.text_input(f"Down Reason", value=u["down_reason"], key=f"downr_{unique_prefix}")
                comment = st.text_area(f"Comment", value=u["comment"], key=f"comment_{unique_prefix}")
                edited_table.append({
                    "vessel": vessel,
                    "date": date,
                    "linear_nm": linear_nm,
                    "square_nm": square_nm,
                    "ping_time": ping_time,
                    "pos_time": pos_time,
                    "acquisition_time": acquisition_time,
                    "down_time": down_time,
                    "down_reason": down_reason,
                    "comment": comment
                })

        download_json = st.form_submit_button("Download Final JSON")
    
    if download_json:
        # --- Recalculate totals from edited table (string form for UI) ---
        total = recalc_totals_from_util(edited_table)
        for key in total:
            total[key] = total[key] if total[key] not in ("", None, "nan", "0", "0.0") else ""
        for u in edited_table:
            for k in ["linear_nm","ping_time","pos_time","square_nm","acquisition_time","down_time"]:
                u[k] = u[k] if u[k] not in ("", None, "nan", "0", "0.0") else ""
    
        # --- Build numeric JSON payload but DO NOT render here ---
        total_numeric = {k: to_number_or_zero(v) for k, v in total.items()}
        utilization_numeric = []
        for u in edited_table:
            utilization_numeric.append({
                "vessel": u["vessel"],
                "date": u["date"],
                "linear_nm": to_number_or_zero(u.get("linear_nm")),
                "square_nm": to_number_or_zero(u.get("square_nm")),
                "ping_time": to_number_or_zero(u.get("ping_time")),
                "pos_time": to_number_or_zero(u.get("pos_time")),
                "acquisition_time": to_number_or_zero(u.get("acquisition_time")),
                "down_time": to_number_or_zero(u.get("down_time")),
                "down_reason": u.get("down_reason") or "",
                "comment": u.get("comment") or ""
            })
    
        header = st.session_state.header_info
        final_json = {
            "project": header["project"],
            "survey": header["survey"],
            "reporting_begin": header["reporting_begin"],
            "reporting_end": header["reporting_end"],
            "fieldwork_begin": header["fieldwork_begin"],
            "fieldwork_end": header["fieldwork_end"],
            "final_report_date": header["final_report_date"],
            "total": total_numeric,
            "utilization": utilization_numeric,
            "last_week_activities": header["last_week_activities"],
            "next_week_activities": header["next_week_activities"]
        }
        
        # Enforce template key order
        final_json = order_final_json(final_json)
        survey_val = header["survey"]
        reporting_begin_fmt = to_yyyymmdd(header["reporting_begin"])
        reporting_end_fmt = to_yyyymmdd(header["reporting_end"])
        file_name = f"{survey_val}_Weekly_Report_{reporting_begin_fmt}_{reporting_end_fmt}.json"
        
        # Store for post-edit rendering and switch UI state
        st.session_state['final_json'] = final_json
        st.session_state['file_name'] = file_name
        st.session_state['reporting_begin_fmt'] = reporting_begin_fmt
        st.session_state['reporting_end_fmt'] = reporting_end_fmt
        st.session_state['show_json_view'] = True
        st.session_state['show_util_edit'] = False
# ---------- Post-Edit JSON Preview/Download ----------
if st.session_state.get("show_json_view", False) and st.session_state.get("final_json"):

    final_json = st.session_state["final_json"]
    file_name = st.session_state.get("file_name", "Weekly_Report.json")
    reporting_begin_fmt = st.session_state.get("reporting_begin_fmt", "YYYYMMDD")
    reporting_end_fmt = st.session_state.get("reporting_end_fmt", "YYYYMMDD")

    st.header("Weekly Report JSON")
    st.code(json.dumps(final_json, indent=4))

    # Unique key per render to avoid duplicate key errors
    st.session_state["download_counter"] = st.session_state.get("download_counter", 0) + 1
    dl_key = f"download_{reporting_begin_fmt}_{reporting_end_fmt}_{st.session_state['download_counter']}"

    st.download_button(
        "Download Final JSON",
        data=json.dumps(final_json, indent=4),
        file_name=file_name,
        mime="application/json",
        key=dl_key
    )