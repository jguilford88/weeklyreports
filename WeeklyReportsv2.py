import streamlit as st
import pandas as pd
import json
import re
import math
from datetime import datetime

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
    if (file.name.endswith('.txt') or file.name.endswith('.csv')) and "Line_Report.txt" in file.name:
        file.seek(0)
        line_report_df = pd.read_csv(file)
    elif file.name.endswith('.log'):
        pos_logs.append(file)
    elif file.name.endswith('.json'):
        previous_json = json.load(file)

default_survey = ""
default_reporting_begin = ""
default_reporting_end = ""

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
        min_times = pd.to_datetime(line_report_df[min_time_col], errors="coerce")
        max_times = pd.to_datetime(line_report_df[max_time_col], errors="coerce")
        min_time_val = min_times.min()
        max_time_val = max_times.max()
        if pd.notnull(min_time_val):
            default_reporting_begin = min_time_val.strftime("%m/%d/%Y")
        if pd.notnull(max_time_val):
            default_reporting_end = max_time_val.strftime("%m/%d/%Y")
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
        try:
            match = prod_df[
                (prod_df["Date"].apply(lambda x: pd.to_datetime(x).strftime("%m/%d/%Y") if pd.notnull(x) else "") == vessel_date)
                &
                (prod_df["Registry Number"].astype(str).str.strip() == survey_registry)
            ]
            if not match.empty:
                row = match.iloc[0]
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

def sum_blanks(vals):
    valsf = [safe_float(v) for v in vals if v not in ("", None)]
    return round2(sum(val for val in valsf if val is not None and val != 0)) if valsf else ""

totals_from_util = {"linear_nm": "", "square_nm": "", "ping_time": "", "pos_time": "", "acquisition_time": "", "down_time": ""}
if util_table:
    for key in totals_from_util:
        vals = [u.get(key, "") for u in util_table]
        totals_from_util[key] = sum_blanks(vals)

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

if submitted and util_table:
    st.subheader("Daily Vessel Utilization")
    edited_table = []
    for idx, u in enumerate(util_table):
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

    # --- Use the latest values from the session state for filename ---
    reporting_begin_val = st.session_state.get("reporting_begin", "")
    reporting_end_val = st.session_state.get("reporting_end", "")
    survey_val = st.session_state.get("survey", "")
    reporting_begin_fmt = to_yyyymmdd(reporting_begin_val)
    reporting_end_fmt = to_yyyymmdd(reporting_end_val)
    file_name = f"{survey_val}_Weekly_Report_{reporting_begin_fmt}_{reporting_end_fmt}.json"

    # Ensure JSON output is blank if the field is blank
    for key in total:
        total[key] = total[key] if total[key] not in ("", None, "nan", "0", "0.0") else ""
    for u in edited_table:
        for k in ["linear_nm","ping_time","pos_time","square_nm","acquisition_time","down_time"]:
            u[k] = u[k] if u[k] not in ("", None, "nan", "0", "0.0") else ""

    final_json = {
        "project": project,
        "survey": survey_val,
        "reporting_begin": reporting_begin_val,
        "reporting_end": reporting_end_val,
        "fieldwork_begin": fieldwork_begin,
        "fieldwork_end": fieldwork_end,
        "final_report_date": final_report_date,
        "total": total,
        "utilization": edited_table,
        "last_week_activities": last_week_activities,
        "next_week_activities": next_week_activities
    }
    st.success("JSON Ready! Download or copy below.")
    st.code(json.dumps(final_json, indent=2))
    st.download_button(
        "Download Final JSON",
        data=json.dumps(final_json, indent=2),
        file_name=file_name,
        mime="application/json"
    )
