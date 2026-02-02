import streamlit as st
import pandas as pd
import plotly.express as px
from streamlit_gsheets import GSheetsConnection
import json
import gspread
import io

# --- CONFIGURATION ---
DEFAULT_CATEGORIES = [
    'Transport', 'Dining', 'Groceries', 'Entertainment', 'Shopping', 
    'Travel', 'Bills & Utilities', 'Transfer/Payment', 'Uncategorized', 
    'Medical', 'Pets', 'Investments', 'Beauty & Spa', 'Education'
]
DEFAULT_SUBCATS = [
    'Coffee', 'Restaurant', 'Flights', 'Hotel', 'Taxi', 'Uber', 'Gas', 
    'Supermarket', 'Online Shopping', 'Subscription', 'General'
]
DEFAULT_PEOPLE = ['Family', 'Partner', 'Business']

DEFAULT_RULES = {
    "uber": {"category": "Transport", "subcategory": "Uber", "person": "Family"}, 
    "starbucks": {"category": "Dining", "subcategory": "Coffee", "person": "Family"},
    "netflix": {"category": "Entertainment", "subcategory": "Subscription", "person": "Family"},
    "taobao": {"category": "Shopping", "subcategory": "Online Shopping", "person": "Family"}
}

st.set_page_config(page_title="Cloud Expense Tracker", layout="wide", page_icon="💳")

# --- 1. SETUP & AUTHENTICATION ---
def check_password():
    def password_entered():
        user = st.session_state["username"].strip()
        password = st.session_state["password"].strip()
        
        if "users" in st.secrets and user in st.secrets["users"] and st.secrets["users"][user] == password:
            st.session_state["password_correct"] = True
            st.session_state["current_user"] = user
            del st.session_state["password"]
            del st.session_state["username"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.title("🔒 Login")
        st.text_input("Username", key="username")
        st.text_input("Password", type="password", key="password", on_change=password_entered)
        return False
    elif not st.session_state["password_correct"]:
        st.title("🔒 Login")
        st.text_input("Username", key="username")
        st.text_input("Password", type="password", key="password", on_change=password_entered)
        st.error("😕 User not found or password incorrect.")
        return False
    else:
        return True

if not check_password():
    st.stop()

# --- 2. CONNECT TO GOOGLE SHEET (Auto-load from secrets) ---
current_user = st.session_state["current_user"]

if "sheets" in st.secrets and current_user in st.secrets["sheets"]:
    sheet_url = st.secrets["sheets"][current_user]
    sheet_connected_via_secrets = True
else:
    sheet_connected_via_secrets = False
    if "sheet_url" not in st.session_state:
        st.session_state["sheet_url"] = ""
    sheet_url = st.session_state.get("sheet_url", "")

if not sheet_url:
    st.title(f"💳 {current_user.title()}'s Cloud Expense Tracker")
    st.warning("⚠️ No Google Sheet configured. Please ask the admin to add your sheet URL to secrets, or enter it below.")
    sheet_url = st.text_input("Paste your Google Sheet Link:")
    if sheet_url:
        st.session_state["sheet_url"] = sheet_url
        st.rerun()
    st.stop()

conn = st.connection("gsheets", type=GSheetsConnection)

# --- HELPER FUNCTIONS ---
@st.cache_resource
def get_gspread_client():
    return gspread.service_account_from_dict(dict(st.secrets["connections"]["gsheets"]))

def ensure_worksheet_exists(tab_name, headers=None):
    try:
        gc = get_gspread_client()
        sh = gc.open_by_url(sheet_url)
        try:
            ws = sh.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=tab_name, rows=1000, cols=20)
            if headers:
                ws.append_row(headers)
            st.toast(f"Created '{tab_name}' tab!")
        return True
    except Exception as e:
        st.error(f"Error ensuring worksheet exists: {e}")
        return False

def load_data(tab_name, default_df=None, headers=None):
    try:
        ensure_worksheet_exists(tab_name, headers)
        df = conn.read(spreadsheet=sheet_url, worksheet=tab_name, ttl=0)
        if df is None or df.empty or (len(df) == 0):
            return default_df if default_df is not None else pd.DataFrame()
        return df
    except Exception:
        return default_df if default_df is not None else pd.DataFrame()

def save_data(df, tab_name, headers=None):
    try:
        ensure_worksheet_exists(tab_name, headers)
        conn.update(spreadsheet=sheet_url, worksheet=tab_name, data=df)
    except Exception as e:
        st.error(f"Error saving to '{tab_name}': {e}")
        raise e

def get_match(description, rules_df):
    desc = str(description).lower()
    if rules_df.empty:
        return None, None, None
    rules_df = rules_df.copy()
    rules_df['kw_len'] = rules_df['Keyword'].str.len()
    rules_df = rules_df.sort_values('kw_len', ascending=False)
    
    for _, row in rules_df.iterrows():
        if str(row['Keyword']).lower() in desc:
            return row['Category'], row.get('SubCategory', ''), row.get('Person', 'Family')
    return None, None, None

# --- Define expected headers ---
HEADERS = {
    "expenses": ['Date', 'Description', 'Amount', 'Category', 'SubCategory', 'Source', 'Person', 'Locked'],
    "categories": ["Category Name"],
    "subcategories": ["Sub-Category Name"],
    "people": ["Person Name"],
    "rules": ["Keyword", "Category", "SubCategory", "Person"]
}

# --- Load Data ---
try:
    df_history = load_data("expenses", headers=HEADERS["expenses"])
    if df_history.empty: 
        df_history = pd.DataFrame(columns=HEADERS["expenses"])
        
    df_cats = load_data("categories", headers=HEADERS["categories"])
    if df_cats.empty: 
        df_cats = pd.DataFrame(DEFAULT_CATEGORIES, columns=["Category Name"])

    df_subs = load_data("subcategories", headers=HEADERS["subcategories"])
    if df_subs.empty: 
        df_subs = pd.DataFrame(DEFAULT_SUBCATS, columns=["Sub-Category Name"])

    df_ppl = load_data("people", headers=HEADERS["people"])
    if df_ppl.empty: 
        df_ppl = pd.DataFrame(DEFAULT_PEOPLE, columns=["Person Name"])

    df_rules = load_data("rules", headers=HEADERS["rules"])
    if df_rules.empty: 
        rules_rows = [{"Keyword": k, "Category": v["category"], "SubCategory": v["subcategory"], "Person": v["person"]} for k, v in DEFAULT_RULES.items()]
        df_rules = pd.DataFrame(rules_rows)

except Exception as e:
    st.error(f"Error connecting to Sheet. Did you share it with the bot?\n\nDetails: {e}")
    st.stop()

# --- PRE-PROCESSING ---
if not df_history.empty:
    df_history['Date'] = pd.to_datetime(df_history['Date'], errors='coerce')
    df_history['SubCategory'] = df_history['SubCategory'].fillna('')
    df_history['Person'] = df_history['Person'].fillna('Family').replace('', 'Family')
    df_history['Category'] = df_history['Category'].fillna('Uncategorized').replace('', 'Uncategorized')
    if 'Locked' not in df_history.columns: 
        df_history['Locked'] = False
    else:
        df_history['Locked'] = df_history['Locked'].fillna(False).astype(bool)
    if 'Create Rule' not in df_history.columns: 
        df_history['Create Rule'] = False

# --- Load lists ---
def get_column_safe(df, col_name):
    if not df.empty and col_name in df.columns:
        return sorted(df[col_name].dropna().unique().tolist())
    return []

if 'categories' not in st.session_state:
    st.session_state['categories'] = get_column_safe(df_cats, "Category Name") or sorted(DEFAULT_CATEGORIES)
if 'subcategories' not in st.session_state:
    st.session_state['subcategories'] = get_column_safe(df_subs, "Sub-Category Name") or sorted(DEFAULT_SUBCATS)
if 'people' not in st.session_state:
    st.session_state['people'] = get_column_safe(df_ppl, "Person Name") or sorted(DEFAULT_PEOPLE)

# --- MAIN TITLE ---
st.title(f"💳 {current_user.title()}'s Cloud Expense Tracker")

# ============================================
# SIDEBAR - REORGANIZED (Filters at Top)
# ============================================

# === SIDEBAR: FILTERS (TOP) ===
st.sidebar.header("🔘 Filters")

if not df_history.empty:
    df_history = df_history.dropna(subset=['Date'])

if not df_history.empty:
    min_date_avail = df_history['Date'].min().date()
    max_date_avail = df_history['Date'].max().date()
    start_date, end_date = st.sidebar.date_input("Period", [min_date_avail, max_date_avail])
    
    search_term = st.sidebar.text_input("Search Description", placeholder="e.g. Starbucks, Uber")

    # Smart lists
    data_people = df_history['Person'].dropna().unique().tolist()
    available_people = sorted(list(set(st.session_state['people'] + data_people)))
    
    data_cats = df_history['Category'].dropna().unique().tolist()
    available_cats = sorted(list(set(st.session_state['categories'] + data_cats)))
    
    data_subs = df_history['SubCategory'].dropna().unique().tolist()
    data_subs = [x for x in data_subs if x != '']
    available_subcats = sorted(list(set(st.session_state['subcategories'] + data_subs)))

    # Filter People
    st.sidebar.markdown("**Filter People**")
    all_people = st.sidebar.checkbox("Select All People", value=True)
    if all_people:
        selected_people = available_people
        st.sidebar.multiselect("Select People", available_people, default=available_people, disabled=True, key="ppl_filter")
    else:
        selected_people = st.sidebar.multiselect("Select People", available_people, default=[], key="ppl_filter")

    # Filter Categories
    st.sidebar.markdown("**Filter Categories**")
    all_cats = st.sidebar.checkbox("Select All Categories", value=False)
    default_cats_view = [c for c in available_cats if c != 'Transfer/Payment']
    if all_cats:
        selected_categories = available_cats
        st.sidebar.multiselect("Select Categories", available_cats, default=available_cats, disabled=True, key="cat_filter")
    else:
        selected_categories = st.sidebar.multiselect("Select Categories", available_cats, default=default_cats_view, key="cat_filter")
    
    # Filter Sub-Categories
    st.sidebar.markdown("**Filter Sub-Categories**")
    all_subs = st.sidebar.checkbox("Select All Sub-Categories", value=True)
    if all_subs:
        selected_subcats = available_subcats
        st.sidebar.multiselect("Select Sub-Cats", available_subcats, default=available_subcats, disabled=True, key="sub_filter")
    else:
        selected_subcats = st.sidebar.multiselect("Select Sub-Cats", available_subcats, default=[], key="sub_filter")

    # Filter Source
    st.sidebar.markdown("**Filter Source**")
    all_sources = st.sidebar.checkbox("Select All Sources", value=True)
    all_sources_list = sorted(df_history['Source'].dropna().unique().tolist())
    if all_sources:
        selected_sources = all_sources_list
        st.sidebar.multiselect("Select Source", all_sources_list, default=all_sources_list, disabled=True, key="src_filter")
    else:
        selected_sources = st.sidebar.multiselect("Select Source", all_sources_list, default=[], key="src_filter")
else:
    start_date, end_date = None, None
    selected_people, selected_categories, selected_subcats, selected_sources = [], [], [], []
    search_term = ""
    available_cats = st.session_state['categories']
    available_subcats = st.session_state['subcategories']
    available_people = st.session_state['people']

st.sidebar.markdown("---")

# === SIDEBAR: MANAGERS ===
with st.sidebar.expander("📂 Manage Categories", expanded=False):
    cat_df = pd.DataFrame(st.session_state['categories'], columns=["Category Name"]).sort_values("Category Name")
    edited_cat_df = st.data_editor(cat_df, num_rows="dynamic", hide_index=True, use_container_width=True, key="cat_editor")
    if st.button("💾 Save Categories"):
        new_cats = sorted(edited_cat_df["Category Name"].dropna().unique().tolist())
        st.session_state['categories'] = new_cats
        save_data(pd.DataFrame(new_cats, columns=["Category Name"]), "categories", HEADERS["categories"])
        st.success("Saved!")
        st.rerun()

with st.sidebar.expander("🏷️ Manage Sub-Categories", expanded=False):
    sub_df = pd.DataFrame(st.session_state['subcategories'], columns=["Sub-Category Name"]).sort_values("Sub-Category Name")
    edited_sub_df = st.data_editor(sub_df, num_rows="dynamic", hide_index=True, use_container_width=True, key="sub_editor")
    if st.button("💾 Save Sub-Categories"):
        new_subs = sorted(edited_sub_df["Sub-Category Name"].dropna().unique().tolist())
        st.session_state['subcategories'] = new_subs
        save_data(pd.DataFrame(new_subs, columns=["Sub-Category Name"]), "subcategories", HEADERS["subcategories"])
        st.success("Saved!")
        st.rerun()

with st.sidebar.expander("👥 Manage People", expanded=False):
    ppl_df = pd.DataFrame(st.session_state['people'], columns=["Person Name"]).sort_values("Person Name")
    edited_ppl_df = st.data_editor(ppl_df, num_rows="dynamic", hide_index=True, use_container_width=True, key="ppl_editor")
    if st.button("💾 Save People"):
        new_ppl = sorted(edited_ppl_df["Person Name"].dropna().unique().tolist())
        st.session_state['people'] = new_ppl
        save_data(pd.DataFrame(new_ppl, columns=["Person Name"]), "people", HEADERS["people"])
        st.success("Saved!")
        st.rerun()

with st.sidebar.expander("📝 Manage Rules", expanded=False):
    sort_option_rules = st.radio("Sort Rules by:", ["Keyword", "Category", "SubCategory"], horizontal=True, key="rule_sort")
    rules_display = df_rules.copy()
    
    if sort_option_rules == "Keyword": 
        rules_display = rules_display.sort_values(by="Keyword")
    elif sort_option_rules == "Category": 
        rules_display = rules_display.sort_values(by=["Category", "Keyword"])
    elif sort_option_rules == "SubCategory": 
        rules_display = rules_display.sort_values(by=["SubCategory", "Keyword"])

    edited_rules = st.data_editor(
        rules_display, num_rows="dynamic", use_container_width=True, hide_index=True, key="rule_editor",
        column_config={
            "Keyword": st.column_config.TextColumn("Keyword", disabled=False),
            "Category": st.column_config.SelectboxColumn("Category", options=st.session_state['categories'], required=True),
            "SubCategory": st.column_config.SelectboxColumn("SubCategory", options=st.session_state['subcategories'], required=False),
            "Person": st.column_config.SelectboxColumn("Person", options=st.session_state['people'], required=True)
        }
    )
    if st.button("💾 Save Rule Changes"):
        edited_rules['Keyword'] = edited_rules['Keyword'].str.lower().str.strip()
        edited_rules = edited_rules.dropna(subset=['Keyword'])
        edited_rules = edited_rules[edited_rules['Keyword'] != '']
        save_data(edited_rules, "rules", HEADERS["rules"])
        df_rules = edited_rules.copy()
        st.success("✅ Rules Updated!")
        st.rerun()

with st.sidebar.expander("🧠 Teach the App", expanded=False):
    new_keyword = st.text_input("Keyword (e.g. Netflix):").lower()
    col_t1, col_t2 = st.columns(2)
    new_cat_rule = col_t1.selectbox("Category:", st.session_state['categories'], key="teach_cat")
    new_sub_rule = col_t2.selectbox("Sub-Category:", [""] + st.session_state['subcategories'], key="teach_sub")
    new_person_rule = st.selectbox("Person:", st.session_state['people'], key="teach_ppl")
    
    if st.button("➕ Add Rule"):
        if new_keyword:
            new_rule_row = pd.DataFrame([{"Keyword": new_keyword, "Category": new_cat_rule, "SubCategory": new_sub_rule, "Person": new_person_rule}])
            df_rules = pd.concat([df_rules, new_rule_row], ignore_index=True).drop_duplicates(subset=['Keyword'], keep='last')
            save_data(df_rules, "rules", HEADERS["rules"])
            st.success(f"Saved! '{new_keyword}' -> {new_cat_rule}")
            st.rerun()
    
    if st.button("🧠 Auto-Learn Rules from History"):
        if not df_history.empty:
            count = 0
            existing_keywords = df_rules['Keyword'].str.lower().tolist() if not df_rules.empty else []
            new_rules_list = []
            
            for index, row in df_history.iterrows():
                desc_key = str(row['Description']).lower().strip()
                if row['Category'] != 'Uncategorized' and desc_key not in existing_keywords:
                    new_rules_list.append({
                        "Keyword": desc_key,
                        "Category": row['Category'],
                        "SubCategory": row.get('SubCategory', ''),
                        "Person": row['Person']
                    })
                    existing_keywords.append(desc_key)
                    count += 1
            
            if new_rules_list:
                new_rules_df = pd.DataFrame(new_rules_list)
                df_rules = pd.concat([df_rules, new_rules_df], ignore_index=True).drop_duplicates(subset=['Keyword'])
                save_data(df_rules, "rules", HEADERS["rules"])
            st.success(f"✅ Learned {count} new rules!")
            st.rerun()

    if st.button("🔄 Re-Apply Rules"):
        if not df_history.empty and not df_rules.empty:
            def apply_complex_rule(row):
                if row.get('Locked', False): 
                    return row
                cat, sub, person = get_match(row['Description'], df_rules)
                if cat: 
                    row['Category'] = cat
                if sub: 
                    row['SubCategory'] = sub
                if person: 
                    row['Person'] = person
                return row
            
            df_history = df_history.apply(apply_complex_rule, axis=1)
            df_history['Date'] = df_history['Date'].astype(str)
            save_history = df_history.drop(columns=['Create Rule'], errors='ignore')
            save_data(save_history, "expenses", HEADERS["expenses"])
            st.success("✅ Rules Re-Applied!")
            st.rerun()

st.sidebar.markdown("---")

# === SIDEBAR: INPUT METHOD ===
st.sidebar.header("📤 Import Data")
input_method = st.sidebar.radio("Input Method:", ["Upload File", "Paste Text"])
new_data = pd.DataFrame()

if input_method == "Upload File":
    uploaded_file = st.sidebar.file_uploader("Upload CSV/Excel", type=["csv", "xlsx"])
    if uploaded_file:
        try:
            if uploaded_file.name.endswith('.csv'): 
                new_data = pd.read_csv(uploaded_file)
            else: 
                new_data = pd.read_excel(uploaded_file)
        except: 
            pass

elif input_method == "Paste Text":
    pasted_text = st.sidebar.text_area("Paste CSV Data", height=150)
    if st.sidebar.button("Process"):
        if pasted_text:
            try: 
                new_data = pd.read_csv(io.StringIO(pasted_text), sep=',')
            except: 
                pass

# --- PROCESS NEW DATA ---
if not new_data.empty:
    try:
        new_data.columns = [str(c).lower().strip() for c in new_data.columns]
        date_col = next((c for c in new_data.columns if 'date' in c), None)
        desc_col = next((c for c in new_data.columns if 'desc' in c or 'memo' in c), None)
        amt_col = next((c for c in new_data.columns if 'amount' in c or 'debit' in c or 'value' in c or 'hkd' in c), None)
        src_col = next((c for c in new_data.columns if 'source' in c), None)
        
        cat_col_in = next((c for c in new_data.columns if 'category' in c and 'sub' not in c), None)
        sub_col_in = next((c for c in new_data.columns if 'sub' in c), None)
        person_col_in = next((c for c in new_data.columns if 'person' in c), None)

        if date_col and desc_col and amt_col:
            new_data[amt_col] = new_data[amt_col].astype(str).str.upper().str.replace('CR','').str.replace('DR','').str.replace(',','').str.replace('$','')
            new_data[amt_col] = pd.to_numeric(new_data[amt_col], errors='coerce')
            source_label = new_data[src_col] if src_col else "Pasted/Uploaded"
            
            clean_new_data = pd.DataFrame({
                'Date': pd.to_datetime(new_data[date_col], errors='coerce'),
                'Description': new_data[desc_col],
                'Amount': new_data[amt_col],
                'Source': source_label,
                'Category': new_data[cat_col_in] if cat_col_in else 'Uncategorized',
                'SubCategory': new_data[sub_col_in] if sub_col_in else '',
                'Person': new_data[person_col_in] if person_col_in else 'Family',
                'Locked': False
            })
            clean_new_data = clean_new_data.dropna(subset=['Date', 'Amount'])
            
            def apply_rules_smart(row):
                if row['Category'] != 'Uncategorized' and pd.notna(row['Category']): 
                    return row
                cat, sub, person = get_match(row['Description'], df_rules)
                if cat: 
                    row['Category'] = cat
                if sub: 
                    row['SubCategory'] = sub
                if person: 
                    row['Person'] = person
                return row
            
            clean_new_data = clean_new_data.apply(apply_rules_smart, axis=1)
            
            df_history_reload = load_data("expenses", headers=HEADERS["expenses"])
            if df_history_reload.empty:
                df_history_reload = pd.DataFrame(columns=HEADERS["expenses"])
            
            combined_df = pd.concat([df_history_reload, clean_new_data]).drop_duplicates(subset=['Date', 'Description', 'Amount'])
            combined_df['Date'] = combined_df['Date'].astype(str)
            save_data(combined_df, "expenses", HEADERS["expenses"])
            st.sidebar.success(f"✅ Added {len(clean_new_data)} transactions!")
            st.rerun()
        else: 
            st.sidebar.error("Headers missing (need Date, Description, Amount).")
    except Exception as e: 
        st.sidebar.error(f"Error: {e}")

st.sidebar.markdown("---")

# === SIDEBAR: SETTINGS (BOTTOM) ===
st.sidebar.header("⚙️ Settings")
font_choice = st.sidebar.select_slider("Aa Text Size", options=["Small", "Default", "Large"], value="Default")
font_size = "14px" if font_choice == "Small" else "20px" if font_choice == "Large" else "16px"
st.markdown(f"<style>html, body, [class*='css'] {{ font-size: {font_size} !important; }}</style>", unsafe_allow_html=True)

st.sidebar.markdown("---")

# === SIDEBAR: CONNECTION INFO (BOTTOM) ===
st.sidebar.header("📌 Connection")
if sheet_connected_via_secrets:
    st.sidebar.success(f"✅ Auto-connected")
    st.sidebar.caption(f"Sheet: ...{sheet_url[-30:]}")
else:
    st.sidebar.info("Manual connection")
    st.sidebar.caption(f"Sheet: ...{sheet_url[-30:]}")
    if st.sidebar.button("🔄 Change Sheet"):
        st.session_state["sheet_url"] = ""
        st.rerun()

st.sidebar.markdown("---")
if st.sidebar.button("🚪 Logout"):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# ============================================
# MAIN DASHBOARD
# ============================================

filtered_df = pd.DataFrame()

if not df_history.empty and start_date and end_date:
    st.subheader(f"📅 PERIOD: {start_date.strftime('%b %d, %Y')} - {end_date.strftime('%b %d, %Y')}")
    st.divider()

    mask = (df_history['Date'].dt.date >= start_date) & \
           (df_history['Date'].dt.date <= end_date) & \
           (df_history['Category'].isin(selected_categories)) & \
           (df_history['SubCategory'].isin(selected_subcats) | (df_history['SubCategory'] == '')) & \
           (df_history['Person'].isin(selected_people)) & \
           (df_history['Source'].isin(selected_sources))
           
    if search_term:
        keywords = [k.strip() for k in search_term.replace(',', ' ').split() if k.strip()]
        if keywords:
            pattern = '|'.join(keywords)
            mask = mask & df_history['Description'].astype(str).str.contains(pattern, case=False, na=False)

    filtered_df = df_history.loc[mask].copy()

    # --- METRICS ---
    total_expense_gross = filtered_df[filtered_df['Amount'] < 0]['Amount'].sum() * -1
    total_refunds = filtered_df[filtered_df['Amount'] > 0]['Amount'].sum()
    net_spend = total_expense_gross - total_refunds
    
    cat_group = filtered_df.groupby('Category')['Amount'].sum().reset_index()
    cat_group['AbsAmount'] = cat_group['Amount'] * -1
    
    p_group = filtered_df.groupby('Person')['Amount'].sum().reset_index()
    p_group['AbsAmount'] = p_group['Amount'] * -1

    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("💸 Net Spend", f"${net_spend:,.2f}")
    col_m2.metric("📉 Total Spend (Gross)", f"${total_expense_gross:,.2f}")
    col_m3.metric("↩️ Refunds/Income", f"${total_refunds:,.2f}")

    col_main_1, col_main_2 = st.columns(2)

    with col_main_1:
        st.subheader("Spending by Category")
        cat_pie = cat_group[cat_group['AbsAmount'] > 0]
        if not cat_pie.empty:
            fig = px.pie(cat_pie, values='AbsAmount', names='Category', hole=0.4)
            st.plotly_chart(fig, use_container_width=True)
            
            st.markdown("##### Category Table")
            cat_display = cat_group.sort_values(by='AbsAmount', ascending=False)
            cat_display['Total'] = cat_display['AbsAmount'].apply(lambda x: f"${x:,.2f}")
            st.dataframe(cat_display[['Category', 'Total']], hide_index=True, use_container_width=True)
            
    with col_main_2:
        st.subheader("Spending by Person")
        p_pie = p_group[p_group['AbsAmount'] > 0]
        if not p_pie.empty:
            fig2 = px.pie(p_pie, values='AbsAmount', names='Person', hole=0.4, color_discrete_sequence=px.colors.qualitative.Set3)
            st.plotly_chart(fig2, use_container_width=True)
            
            st.markdown("##### Person Table")
            p_display = p_group.sort_values(by='AbsAmount', ascending=False)
            p_display['Total'] = p_display['AbsAmount'].apply(lambda x: f"${x:,.2f}")
            st.dataframe(p_display[['Person', 'Total']], hide_index=True, use_container_width=True)

    # --- DEEP DIVE ---
    st.markdown("---")
    st.subheader("📊 Category Deep Dive")
    col_dd1, col_dd2 = st.columns([1, 1])

    with col_dd1:
        st.markdown("**1. Select a Category:**")
        cat_master = cat_group[cat_group['AbsAmount'] > 0].sort_values(by='AbsAmount', ascending=False)
        cat_master['Total'] = cat_master['AbsAmount'].apply(lambda x: f"${x:,.2f}")
        selection = st.dataframe(cat_master[['Category', 'Total']], use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")
    
    with col_dd2:
        st.markdown("**2. Sub-Category Breakdown:**")
        if selection.selection.rows:
            selected_idx = selection.selection.rows[0]
            selected_cat = cat_master.iloc[selected_idx]['Category']
            subset_df = filtered_df[filtered_df['Category'] == selected_cat].copy()
            sub_breakdown = subset_df.groupby('SubCategory')['Amount'].sum().reset_index()
            sub_breakdown['AbsAmount'] = sub_breakdown['Amount'] * -1
            sub_breakdown = sub_breakdown.sort_values(by='AbsAmount', ascending=False)
            sub_breakdown['Total'] = sub_breakdown['AbsAmount'].apply(lambda x: f"${x:,.2f}")
            st.info(f"Drilling down into: **{selected_cat}**")
            st.dataframe(sub_breakdown[['SubCategory', 'Total']], use_container_width=True, hide_index=True)
        else:
            st.info("👈 Click a Category on the left to see details here.")

    # --- TRANSACTION EDITOR ---
    st.markdown("---")
    st.subheader("📝 Transaction Editor")
    
    col_sort, col_lock_btn = st.columns([3, 1])
    
    sort_option = col_sort.selectbox(
        "Sort By:", 
        [
            "Native (Click Headers to Sort)", 
            "Date (Newest)", 
            "Date (Oldest)", 
            "Amount (Lowest first - Big Spends)", 
            "Amount (Highest first - Income)", 
            "Description (A-Z)", 
            "Description (Z-A)"
        ]
    )
    
    if col_lock_btn.button("🔒 Lock All Shown"):
        if not filtered_df.empty:
            df_history.loc[filtered_df.index, 'Locked'] = True
            df_history['Date'] = df_history['Date'].astype(str)
            save_history = df_history.drop(columns=['Create Rule'], errors='ignore')
            save_data(save_history, "expenses", HEADERS["expenses"])
            st.success("Locked!")
            st.rerun()

    if not filtered_df.empty:
        filtered_df_display = filtered_df.copy()
        
        if sort_option == "Date (Newest)":
            filtered_df_display = filtered_df_display.sort_values(by="Date", ascending=False)
        elif sort_option == "Date (Oldest)":
            filtered_df_display = filtered_df_display.sort_values(by="Date", ascending=True)
        elif sort_option == "Amount (Lowest first - Big Spends)":
            filtered_df_display = filtered_df_display.sort_values(by="Amount", ascending=True)
        elif sort_option == "Amount (Highest first - Income)":
            filtered_df_display = filtered_df_display.sort_values(by="Amount", ascending=False)
        elif sort_option == "Description (A-Z)":
            filtered_df_display = filtered_df_display.sort_values(by="Description", ascending=True)
        elif sort_option == "Description (Z-A)":
            filtered_df_display = filtered_df_display.sort_values(by="Description", ascending=False)

        filtered_df_display['Date'] = filtered_df_display['Date'].dt.date
        
        if 'Create Rule' not in filtered_df_display.columns:
            filtered_df_display['Create Rule'] = False
        
        filtered_df_display['Create Rule'] = filtered_df_display['Create Rule'].fillna(False).astype(bool)
        filtered_df_display['Locked'] = filtered_df_display['Locked'].fillna(False).astype(bool)
        
        filtered_df_display = filtered_df_display[['Date', 'Description', 'Amount', 'Category', 'SubCategory', 'Person', 'Source', 'Locked', 'Create Rule']]
        
        edited_df = st.data_editor(
            filtered_df_display,
            column_config={
                "Locked": st.column_config.CheckboxColumn("🔒", width="small"),
                "Create Rule": st.column_config.CheckboxColumn("➕ Rule", width="small", help="Check this box and click 'Save Changes' to create a permanent rule for this item."),
                "Category": st.column_config.SelectboxColumn("Category", options=available_cats, required=True),
                "SubCategory": st.column_config.SelectboxColumn("Sub-Category", options=available_subcats, required=False),
                "Person": st.column_config.SelectboxColumn("Person", options=available_people, required=True),
                "Source": st.column_config.TextColumn("Source", disabled=True),
                "Amount": st.column_config.NumberColumn("Amount", format="$%.2f"),
                "Date": st.column_config.DateColumn("Date")
            },
            hide_index=True, 
            use_container_width=True, 
            num_rows="dynamic", 
            height=500
        )
        
        if st.button("💾 Save Changes & Create Rules"):
            # Handle deletions
            original_indices = filtered_df.index.tolist()
            remaining_indices = edited_df.index.tolist()
            deleted_indices = list(set(original_indices) - set(remaining_indices))
            
            if deleted_indices:
                df_history = df_history.drop(deleted_indices)

            # Handle rules
            rules_created = 0
            new_cats_added = False
            new_subs_added = False
            
            for index, row in edited_df.iterrows():
                if row.get('Create Rule', False):
                    desc_text = str(row['Description']).lower().strip()
                    cat = row['Category']
                    sub = row['SubCategory']
                    person = row['Person']
                    
                    new_rule_row = pd.DataFrame([{"Keyword": desc_text, "Category": cat, "SubCategory": sub, "Person": person}])
                    df_rules = pd.concat([df_rules, new_rule_row], ignore_index=True).drop_duplicates(subset=['Keyword'], keep='last')
                    rules_created += 1
                    
                    if cat not in st.session_state['categories']:
                        st.session_state['categories'].append(cat)
                        st.session_state['categories'].sort()
                        new_cats_added = True
                    
                    if sub and sub not in st.session_state['subcategories']:
                        st.session_state['subcategories'].append(sub)
                        st.session_state['subcategories'].sort()
                        new_subs_added = True
                    
                    edited_df.at[index, 'Create Rule'] = False
                    edited_df.at[index, 'Locked'] = True

            if rules_created > 0:
                save_data(df_rules, "rules", HEADERS["rules"])
                if new_cats_added: 
                    save_data(pd.DataFrame(st.session_state['categories'], columns=["Category Name"]), "categories", HEADERS["categories"])
                if new_subs_added: 
                    save_data(pd.DataFrame(st.session_state['subcategories'], columns=["Sub-Category Name"]), "subcategories", HEADERS["subcategories"])
                
                st.toast(f"✅ Created {rules_created} new rules!", icon="🧠")

            # Save data updates
            common_indices = list(set(df_history.index).intersection(remaining_indices))
            save_df = edited_df.drop(columns=['Create Rule'], errors='ignore')
            df_history.loc[common_indices] = save_df.loc[common_indices]
            
            df_history['Date'] = pd.to_datetime(df_history['Date']).astype(str)
            save_history = df_history.drop(columns=['Create Rule'], errors='ignore')
            save_data(save_history, "expenses", HEADERS["expenses"])
            st.success("✅ Changes Saved!")
            st.rerun()

else:
    st.info("👋 Upload a file or Paste Text in the sidebar to begin!")
