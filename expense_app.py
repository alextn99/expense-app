import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client
import io
import datetime

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
    "uber": {"name": "Uber Ride", "category": "Transport", "subcategory": "Uber", "person": "Family"}, 
    "starbucks": {"name": "Starbucks Coffee", "category": "Dining", "subcategory": "Coffee", "person": "Family"},
    "netflix": {"name": "Netflix Subscription", "category": "Entertainment", "subcategory": "Subscription", "person": "Family"},
    "taobao": {"name": "Taobao Purchase", "category": "Shopping", "subcategory": "Online Shopping", "person": "Family"}
}

st.set_page_config(page_title="Cloud Expense Tracker", layout="wide", page_icon="💳")

# ============================================
# 1. AUTHENTICATION
# ============================================
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

# ============================================
# 2. SUPABASE CONNECTION (Per-User Project)
# ============================================
current_user = st.session_state["current_user"]

if "supabase" in st.secrets and f"{current_user}_url" in st.secrets["supabase"]:
    sb_url = st.secrets["supabase"][f"{current_user}_url"]
    sb_key = st.secrets["supabase"][f"{current_user}_key"]
    db_connected = True
else:
    db_connected = False

if not db_connected:
    st.title(f"💳 {current_user.title()}'s Cloud Expense Tracker")
    st.error(f"⚠️ No database configured for '{current_user}'. Ask the admin to add Supabase credentials to secrets.")
    st.stop()

@st.cache_resource
def get_supabase_client(_url, _key):
    return create_client(_url, _key)

sb = get_supabase_client(sb_url, sb_key)

# ============================================
# 3. DATA ACCESS FUNCTIONS
# ============================================

# Column mappings: DB (lowercase) <-> App (CamelCase)
EXP_COLS = {
    'date': 'Date', 'description': 'Description', 'amount': 'Amount',
    'name': 'Name', 'category': 'Category', 'subcategory': 'SubCategory', 
    'source': 'Source', 'person': 'Person', 'locked': 'Locked'
}
EXP_COLS_REV = {v: k for k, v in EXP_COLS.items()}

RULES_COLS = {
    'keyword': 'Keyword', 'name': 'Name', 'category': 'Category',
    'subcategory': 'SubCategory', 'person': 'Person', 'amount': 'Amount'
}
RULES_COLS_REV = {v: k for k, v in RULES_COLS.items()}

def prepare_records(df):
    """Convert DataFrame to clean list of dicts for Supabase."""
    records = []
    for _, row in df.iterrows():
        record = {}
        for col, val in row.items():
            if isinstance(val, bool):
                record[col] = val
            elif pd.isna(val):
                record[col] = None
            elif isinstance(val, (pd.Timestamp, datetime.datetime)):
                record[col] = val.strftime('%Y-%m-%d')
            elif isinstance(val, datetime.date):
                record[col] = val.strftime('%Y-%m-%d')
            elif hasattr(val, 'item'):
                record[col] = val.item()
            else:
                record[col] = val
        records.append(record)
    return records

# --- EXPENSES ---
def load_expenses():
    try:
        resp = sb.table("expenses").select("*").execute()
        if resp.data:
            df = pd.DataFrame(resp.data)
            df = df.rename(columns=EXP_COLS)
            return df
        return pd.DataFrame(columns=['id'] + list(EXP_COLS.values()))
    except Exception as e:
        st.error(f"Error loading expenses: {e}")
        return pd.DataFrame(columns=['id'] + list(EXP_COLS.values()))

def insert_expenses(df):
    """Insert new rows (no id — DB auto-generates)."""
    df_save = df.rename(columns=EXP_COLS_REV)
    if 'id' in df_save.columns:
        df_save = df_save.drop(columns=['id'])
    valid_cols = list(EXP_COLS_REV.values())
    df_save = df_save[[c for c in df_save.columns if c in valid_cols]]
    records = prepare_records(df_save)
    if records:
        sb.table("expenses").insert(records).execute()

def upsert_expenses(df):
    """Update existing rows (must include id)."""
    df_save = df.rename(columns=EXP_COLS_REV)
    valid_cols = ['id'] + list(EXP_COLS_REV.values())
    df_save = df_save[[c for c in df_save.columns if c in valid_cols]]
    df_save['id'] = df_save['id'].astype(int)
    records = prepare_records(df_save)
    if records:
        sb.table("expenses").upsert(records).execute()

def delete_expenses(ids):
    """Delete rows by id."""
    for id_val in ids:
        sb.table("expenses").delete().eq("id", int(id_val)).execute()

# --- REFERENCE LISTS (categories, subcategories, people) ---
def load_list(table_name):
    try:
        resp = sb.table(table_name).select("name").execute()
        if resp.data:
            return sorted([r['name'] for r in resp.data if r.get('name')])
        return []
    except:
        return []

def save_list(table_name, items):
    """Replace all items in a reference table."""
    try:
        sb.table(table_name).delete().gte("id", 0).execute()
        if items:
            sb.table(table_name).insert([{"name": item} for item in items if item]).execute()
    except Exception as e:
        st.error(f"Error saving {table_name}: {e}")

# --- RULES ---
def load_rules():
    try:
        resp = sb.table("rules").select("*").execute()
        if resp.data:
            df = pd.DataFrame(resp.data)
            df = df.rename(columns=RULES_COLS)
            return df
        return pd.DataFrame(columns=['id'] + list(RULES_COLS.values()))
    except:
        return pd.DataFrame(columns=['id'] + list(RULES_COLS.values()))

def save_rules_full(df):
    """Replace ALL rules (delete + insert)."""
    try:
        sb.table("rules").delete().gte("id", 0).execute()
        df_save = df.rename(columns=RULES_COLS_REV)
        if 'id' in df_save.columns:
            df_save = df_save.drop(columns=['id'])
        valid_cols = list(RULES_COLS_REV.values())
        df_save = df_save[[c for c in df_save.columns if c in valid_cols]]
        records = prepare_records(df_save)
        if records:
            sb.table("rules").insert(records).execute()
    except Exception as e:
        st.error(f"Error saving rules: {e}")

def add_rules(new_rules_df):
    """Add new rules (upsert on keyword conflict)."""
    df_save = new_rules_df.rename(columns=RULES_COLS_REV)
    if 'id' in df_save.columns:
        df_save = df_save.drop(columns=['id'])
    valid_cols = list(RULES_COLS_REV.values())
    df_save = df_save[[c for c in df_save.columns if c in valid_cols]]
    records = prepare_records(df_save)
    if records:
        sb.table("rules").upsert(records, on_conflict="keyword").execute()

# --- RULE MATCHING ---
def get_match(description, amount, rules_df):
    """Match description and optionally exact amount to return name, category, subcategory, person."""
    desc = str(description).lower()
    if rules_df.empty:
        return None, None, None, None
    
    rules_sorted = rules_df.copy()
    rules_sorted['_kw_len'] = rules_sorted['Keyword'].str.len()
    rules_sorted = rules_sorted.sort_values('_kw_len', ascending=False)
    
    for _, row in rules_sorted.iterrows():
        if str(row['Keyword']).lower() in desc:
            # Check exact amount if specified in rule
            rule_amount = row.get('Amount')
            
            if pd.notna(rule_amount) and rule_amount is not None:
                if amount is None or abs(float(amount) - float(rule_amount)) > 0.01:
                    continue
            
            return (
                row.get('Name', '') if pd.notna(row.get('Name')) else '',
                row['Category'], 
                row.get('SubCategory', '') if pd.notna(row.get('SubCategory')) else '', 
                row.get('Person', 'Family') if pd.notna(row.get('Person')) else 'Family'
            )
    return None, None, None, None

# ============================================
# 4. LOAD ALL DATA
# ============================================
try:
    df_history = load_expenses()
    df_rules = load_rules()
    
    loaded_cats = load_list("categories")
    loaded_subcats = load_list("subcategories")
    loaded_people = load_list("people")
    
    if not loaded_cats:
        save_list("categories", DEFAULT_CATEGORIES)
        loaded_cats = sorted(DEFAULT_CATEGORIES)
    if not loaded_subcats:
        save_list("subcategories", DEFAULT_SUBCATS)
        loaded_subcats = sorted(DEFAULT_SUBCATS)
    if not loaded_people:
        save_list("people", DEFAULT_PEOPLE)
        loaded_people = sorted(DEFAULT_PEOPLE)
    
    if df_rules.empty:
        seed_rules = [
            {
                "Keyword": k, 
                "Name": v["name"],
                "Category": v["category"], 
                "SubCategory": v["subcategory"], 
                "Person": v["person"],
                "Amount": None
            } 
            for k, v in DEFAULT_RULES.items()
        ]
        df_rules = pd.DataFrame(seed_rules)
        save_rules_full(df_rules)
        df_rules = load_rules()

except Exception as e:
    st.error(f"Error connecting to database.\n\nDetails: {e}")
    st.stop()

# ============================================
# 5. PRE-PROCESSING
# ============================================
if not df_history.empty:
    df_history['Date'] = pd.to_datetime(df_history['Date'], errors='coerce')
    df_history['Name'] = df_history['Name'].fillna('') if 'Name' in df_history.columns else ''
    df_history['SubCategory'] = df_history['SubCategory'].fillna('')
    df_history['Person'] = df_history['Person'].fillna('Family').replace('', 'Family')
    df_history['Category'] = df_history['Category'].fillna('Uncategorized').replace('', 'Uncategorized')
    df_history['Source'] = df_history['Source'].fillna('').replace('', 'Unknown')
    if 'Locked' not in df_history.columns:
        df_history['Locked'] = False
    else:
        df_history['Locked'] = df_history['Locked'].fillna(False).astype(bool)
    if 'Name' not in df_history.columns:
        df_history['Name'] = ''

if not df_rules.empty:
    if 'Name' not in df_rules.columns:
        df_rules['Name'] = ''
    if 'Amount' not in df_rules.columns:
        df_rules['Amount'] = None

# ============================================
# 6. SESSION STATE INIT
# ============================================
if 'categories' not in st.session_state:
    st.session_state['categories'] = loaded_cats
if 'subcategories' not in st.session_state:
    st.session_state['subcategories'] = loaded_subcats
if 'people' not in st.session_state:
    st.session_state['people'] = loaded_people

# ============================================
# MAIN TITLE
# ============================================
st.title(f"💳 {current_user.title()}'s Cloud Expense Tracker")

# ============================================
# SIDEBAR (Filters at Top, Settings at Bottom)
# ============================================

# === FILTERS (TOP) ===
st.sidebar.header("🔘 Filters")

if not df_history.empty:
    df_history = df_history.dropna(subset=['Date'])

if not df_history.empty:
    min_date_avail = df_history['Date'].min().date()
    max_date_avail = df_history['Date'].max().date()
    start_date, end_date = st.sidebar.date_input("Period", [min_date_avail, max_date_avail])
    
    # Search with toggle for Name/Description/Both
    search_field = st.sidebar.radio("Search in:", ["Name", "Description", "Both"], horizontal=True, index=2)
    search_term = st.sidebar.text_input("Search", placeholder="e.g. Starbucks, Uber")

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
    search_field = "Both"
    available_cats = st.session_state['categories']
    available_subcats = st.session_state['subcategories']
    available_people = st.session_state['people']

st.sidebar.markdown("---")

# === MANAGERS ===
with st.sidebar.expander("📂 Manage Categories", expanded=False):
    cat_df = pd.DataFrame(st.session_state['categories'], columns=["Category Name"]).sort_values("Category Name")
    edited_cat_df = st.data_editor(cat_df, num_rows="dynamic", hide_index=True, use_container_width=True, key="cat_editor")
    if st.button("💾 Save Categories"):
        new_cats = sorted(edited_cat_df["Category Name"].dropna().unique().tolist())
        st.session_state['categories'] = new_cats
        save_list("categories", new_cats)
        st.success("Saved!")
        st.rerun()

with st.sidebar.expander("🏷️ Manage Sub-Categories", expanded=False):
    sub_df = pd.DataFrame(st.session_state['subcategories'], columns=["Sub-Category Name"]).sort_values("Sub-Category Name")
    edited_sub_df = st.data_editor(sub_df, num_rows="dynamic", hide_index=True, use_container_width=True, key="sub_editor")
    if st.button("💾 Save Sub-Categories"):
        new_subs = sorted(edited_sub_df["Sub-Category Name"].dropna().unique().tolist())
        st.session_state['subcategories'] = new_subs
        save_list("subcategories", new_subs)
        st.success("Saved!")
        st.rerun()

with st.sidebar.expander("👥 Manage People", expanded=False):
    ppl_df = pd.DataFrame(st.session_state['people'], columns=["Person Name"]).sort_values("Person Name")
    edited_ppl_df = st.data_editor(ppl_df, num_rows="dynamic", hide_index=True, use_container_width=True, key="ppl_editor")
    if st.button("💾 Save People"):
        new_ppl = sorted(edited_ppl_df["Person Name"].dropna().unique().tolist())
        st.session_state['people'] = new_ppl
        save_list("people", new_ppl)
        st.success("Saved!")
        st.rerun()

with st.sidebar.expander("📝 Manage Rules", expanded=False):
    sort_option_rules = st.radio("Sort Rules by:", ["Keyword", "Name", "Category", "SubCategory"], horizontal=True, key="rule_sort")
    rules_display = df_rules.drop(columns=['id'], errors='ignore').copy()
    
    for col in ['Keyword', 'Name', 'Category', 'SubCategory', 'Person', 'Amount']:
        if col not in rules_display.columns:
            rules_display[col] = None if col == 'Amount' else ''
    
    if sort_option_rules == "Keyword": 
        rules_display = rules_display.sort_values(by="Keyword")
    elif sort_option_rules == "Name": 
        rules_display = rules_display.sort_values(by=["Name", "Keyword"])
    elif sort_option_rules == "Category": 
        rules_display = rules_display.sort_values(by=["Category", "Keyword"])
    elif sort_option_rules == "SubCategory": 
        rules_display = rules_display.sort_values(by=["SubCategory", "Keyword"])

    edited_rules = st.data_editor(
        rules_display, num_rows="dynamic", use_container_width=True, hide_index=True, key="rule_editor",
        column_config={
            "Keyword": st.column_config.TextColumn("Keyword", disabled=False),
            "Name": st.column_config.TextColumn("Name", help="Friendly name to assign"),
            "Category": st.column_config.SelectboxColumn("Category", options=st.session_state['categories'], required=True),
            "SubCategory": st.column_config.SelectboxColumn("SubCategory", options=st.session_state['subcategories'], required=False),
            "Person": st.column_config.SelectboxColumn("Person", options=st.session_state['people'], required=True),
            "Amount": st.column_config.NumberColumn("Amount", help="Optional: Only match if amount equals this exactly", format="%.2f")
        }
    )
    if st.button("💾 Save Rule Changes"):
        edited_rules['Keyword'] = edited_rules['Keyword'].str.lower().str.strip()
        edited_rules = edited_rules.dropna(subset=['Keyword'])
        edited_rules = edited_rules[edited_rules['Keyword'] != '']
        save_rules_full(edited_rules)
        df_rules = load_rules()
        st.success("✅ Rules Updated!")
        st.rerun()

with st.sidebar.expander("🧠 Teach the App", expanded=False):
    new_keyword = st.text_input("Keyword (e.g. Netflix):").lower()
    new_name = st.text_input("Name (e.g. Netflix Subscription):")
    col_t1, col_t2 = st.columns(2)
    new_cat_rule = col_t1.selectbox("Category:", st.session_state['categories'], key="teach_cat")
    new_sub_rule = col_t2.selectbox("Sub-Category:", [""] + st.session_state['subcategories'], key="teach_sub")
    new_person_rule = st.selectbox("Person:", st.session_state['people'], key="teach_ppl")
    
    new_amount = st.number_input("Exact Amount (optional)", value=None, step=0.01, key="teach_amt", help="Leave blank to match any amount")
    
    if st.button("➕ Add Rule"):
        if new_keyword:
            new_rule_row = pd.DataFrame([{
                "Keyword": new_keyword, 
                "Name": new_name,
                "Category": new_cat_rule, 
                "SubCategory": new_sub_rule, 
                "Person": new_person_rule,
                "Amount": new_amount
            }])
            add_rules(new_rule_row)
            st.success(f"Saved! '{new_keyword}' -> {new_name} ({new_cat_rule})")
            st.rerun()
    
    if st.button("🧠 Auto-Learn Rules from History"):
        if not df_history.empty:
            existing_keywords = df_rules['Keyword'].str.lower().tolist() if not df_rules.empty else []
            new_rules_list = []
            
            for _, row in df_history.iterrows():
                desc_key = str(row['Description']).lower().strip()
                if row['Category'] != 'Uncategorized' and desc_key not in existing_keywords:
                    new_rules_list.append({
                        "Keyword": desc_key,
                        "Name": row.get('Name', '') if pd.notna(row.get('Name')) else '',
                        "Category": row['Category'],
                        "SubCategory": row.get('SubCategory', ''),
                        "Person": row['Person'],
                        "Amount": None
                    })
                    existing_keywords.append(desc_key)
            
            if new_rules_list:
                add_rules(pd.DataFrame(new_rules_list))
            st.success(f"✅ Learned {len(new_rules_list)} new rules!")
            st.rerun()

    if st.button("🔄 Re-Apply Rules"):
        if not df_history.empty and not df_rules.empty:
            changed_ids = []
            for idx, row in df_history.iterrows():
                if row.get('Locked', False):
                    continue
                name, cat, sub, person = get_match(row['Description'], row['Amount'], df_rules)
                if name:
                    df_history.at[idx, 'Name'] = name
                if cat:
                    df_history.at[idx, 'Category'] = cat
                if sub:
                    df_history.at[idx, 'SubCategory'] = sub
                if person:
                    df_history.at[idx, 'Person'] = person
                if name or cat or sub or person:
                    changed_ids.append(idx)
            
            if changed_ids:
                upsert_expenses(df_history.loc[changed_ids])
            st.success(f"✅ Rules Re-Applied to {len(changed_ids)} transactions!")
            st.rerun()

st.sidebar.markdown("---")

# === IMPORT DATA (with Manual Source) ===
st.sidebar.header("📤 Import Data")

manual_source = st.sidebar.text_input("Source Name", placeholder="e.g. HSBC Credit, Chase Debit", key="source_input")

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
        
        name_col_in = next((c for c in new_data.columns if c == 'name'), None)
        cat_col_in = next((c for c in new_data.columns if 'category' in c and 'sub' not in c), None)
        sub_col_in = next((c for c in new_data.columns if 'sub' in c), None)
        person_col_in = next((c for c in new_data.columns if 'person' in c), None)

        if date_col and desc_col and amt_col:
            new_data[amt_col] = new_data[amt_col].astype(str).str.upper().str.replace('CR','').str.replace('DR','').str.replace(',','').str.replace('$','')
            new_data[amt_col] = pd.to_numeric(new_data[amt_col], errors='coerce')
            
            if src_col:
                file_source = new_data[src_col]
            elif manual_source:
                file_source = manual_source
            else:
                file_source = "Pasted/Uploaded"
            
            clean_new_data = pd.DataFrame({
                'Date': pd.to_datetime(new_data[date_col], errors='coerce'),
                'Description': new_data[desc_col],
                'Amount': new_data[amt_col],
                'Source': file_source,
                'Name': new_data[name_col_in] if name_col_in else '',
                'Category': new_data[cat_col_in] if cat_col_in else 'Uncategorized',
                'SubCategory': new_data[sub_col_in] if sub_col_in else '',
                'Person': new_data[person_col_in] if person_col_in else 'Family',
                'Locked': False
            })
            clean_new_data = clean_new_data.dropna(subset=['Date', 'Amount'])
            
            def apply_rules_smart(row):
                if row['Category'] != 'Uncategorized' and pd.notna(row['Category']) and row.get('Name', '') != '': 
                    return row
                
                name, cat, sub, person = get_match(row['Description'], row['Amount'], df_rules)
                
                if name and (row.get('Name', '') == '' or pd.isna(row.get('Name', ''))):
                    row['Name'] = name
                if cat and (row['Category'] == 'Uncategorized' or pd.isna(row['Category'])): 
                    row['Category'] = cat
                if sub and (row.get('SubCategory', '') == '' or pd.isna(row.get('SubCategory', ''))): 
                    row['SubCategory'] = sub
                if person and (row.get('Person', '') == '' or pd.isna(row.get('Person', ''))): 
                    row['Person'] = person
                return row
            
            clean_new_data = clean_new_data.apply(apply_rules_smart, axis=1)
            
            existing = load_expenses()
            if not existing.empty:
                existing['_key'] = existing['Date'].astype(str) + '|' + existing['Description'].astype(str) + '|' + existing['Amount'].astype(str)
                clean_new_data['_key'] = clean_new_data['Date'].astype(str) + '|' + clean_new_data['Description'].astype(str) + '|' + clean_new_data['Amount'].astype(str)
                truly_new = clean_new_data[~clean_new_data['_key'].isin(existing['_key'])].drop(columns=['_key'])
            else:
                truly_new = clean_new_data
            
            if not truly_new.empty:
                insert_expenses(truly_new)
                st.sidebar.success(f"✅ Added {len(truly_new)} new transactions!")
                if len(truly_new) < len(clean_new_data):
                    st.sidebar.info(f"ℹ️ Skipped {len(clean_new_data) - len(truly_new)} duplicates.")
            else:
                st.sidebar.warning("⚠️ All transactions already exist (duplicates).")
            st.rerun()
        else: 
            st.sidebar.error("Headers missing (need Date, Description, Amount).")
    except Exception as e: 
        st.sidebar.error(f"Error: {e}")

st.sidebar.markdown("---")

# === SETTINGS (BOTTOM) ===
st.sidebar.header("⚙️ Settings")
font_choice = st.sidebar.select_slider("Aa Text Size", options=["Small", "Default", "Large"], value="Default")
font_size = "14px" if font_choice == "Small" else "20px" if font_choice == "Large" else "16px"
st.markdown(f"<style>html, body, [class*='css'] {{ font-size: {font_size} !important; }}</style>", unsafe_allow_html=True)

st.sidebar.markdown("---")

# === CONNECTION INFO (BOTTOM) ===
st.sidebar.header("📌 Connection")
st.sidebar.success("✅ Connected to Supabase")
st.sidebar.caption(f"Project: ...{sb_url[-25:]}")

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
            if search_field == "Name":
                mask = mask & df_history['Name'].astype(str).str.contains(pattern, case=False, na=False)
            elif search_field == "Description":
                mask = mask & df_history['Description'].astype(str).str.contains(pattern, case=False, na=False)
            else:
                mask = mask & (
                    df_history['Name'].astype(str).str.contains(pattern, case=False, na=False) |
                    df_history['Description'].astype(str).str.contains(pattern, case=False, na=False)
                )

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
            "Name (A-Z)",
            "Name (Z-A)",
            "Description (A-Z)", 
            "Description (Z-A)"
        ]
    )
    
    if col_lock_btn.button("🔒 Lock All Shown"):
        if not filtered_df.empty:
            filtered_df['Locked'] = True
            upsert_expenses(filtered_df)
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
        elif sort_option == "Name (A-Z)":
            filtered_df_display = filtered_df_display.sort_values(by="Name", ascending=True)
        elif sort_option == "Name (Z-A)":
            filtered_df_display = filtered_df_display.sort_values(by="Name", ascending=False)
        elif sort_option == "Description (A-Z)":
            filtered_df_display = filtered_df_display.sort_values(by="Description", ascending=True)
        elif sort_option == "Description (Z-A)":
            filtered_df_display = filtered_df_display.sort_values(by="Description", ascending=False)

        filtered_df_display['Date'] = filtered_df_display['Date'].dt.date
        
        # Add UI-only columns for rule creation
        filtered_df_display['Create Rule'] = False
        filtered_df_display['Include Amt'] = False
        filtered_df_display['Locked'] = filtered_df_display['Locked'].fillna(False).astype(bool)
        
        if 'Name' not in filtered_df_display.columns:
            filtered_df_display['Name'] = ''
        
        # Reorder columns
        display_cols = ['id', 'Date', 'Name', 'Description', 'Amount', 'Category', 'SubCategory', 'Person', 'Source', 'Locked', 'Create Rule', 'Include Amt']
        filtered_df_display = filtered_df_display[[c for c in display_cols if c in filtered_df_display.columns]]
        
        edited_df = st.data_editor(
            filtered_df_display,
            column_config={
                "id": None,
                "Locked": st.column_config.CheckboxColumn("🔒", width="small"),
                "Create Rule": st.column_config.CheckboxColumn("➕ Rule", width="small", help="Create a rule from this transaction"),
                "Include Amt": st.column_config.CheckboxColumn("💲 Amt", width="small", help="Include exact amount in the rule"),
                "Name": st.column_config.TextColumn("Name", help="Friendly name for this transaction"),
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
            # 1. HANDLE DELETIONS
            original_ids = set(filtered_df_display['id'].dropna().tolist())
            remaining_ids = set(edited_df['id'].dropna().tolist()) if 'id' in edited_df.columns else set()
            deleted_ids = original_ids - remaining_ids
            
            if deleted_ids:
                delete_expenses(list(deleted_ids))
                st.toast(f"🗑️ Deleted {len(deleted_ids)} transactions")

            # 2. HANDLE RULES
            rules_created = 0
            new_cats_added = False
            new_subs_added = False
            
            for idx, row in edited_df.iterrows():
                if row.get('Create Rule', False):
                    desc_text = str(row['Description']).lower().strip()
                    name = row.get('Name', '')
                    cat = row['Category']
                    sub = row.get('SubCategory', '')
                    person = row.get('Person', 'Family')
                    
                    # Include amount only if checkbox is checked
                    rule_amount = row['Amount'] if row.get('Include Amt', False) else None
                    
                    new_rule = pd.DataFrame([{
                        "Keyword": desc_text, 
                        "Name": name,
                        "Category": cat, 
                        "SubCategory": sub, 
                        "Person": person,
                        "Amount": rule_amount
                    }])
                    add_rules(new_rule)
                    rules_created += 1
                    
                    if cat not in st.session_state['categories']:
                        st.session_state['categories'].append(cat)
                        st.session_state['categories'].sort()
                        new_cats_added = True
                    
                    if sub and sub not in st.session_state['subcategories']:
                        st.session_state['subcategories'].append(sub)
                        st.session_state['subcategories'].sort()
                        new_subs_added = True
                    
                    edited_df.at[idx, 'Create Rule'] = False
                    edited_df.at[idx, 'Include Amt'] = False
                    edited_df.at[idx, 'Locked'] = True

            if rules_created > 0:
                if new_cats_added: 
                    save_list("categories", st.session_state['categories'])
                if new_subs_added: 
                    save_list("subcategories", st.session_state['subcategories'])
                st.toast(f"✅ Created {rules_created} new rules!", icon="🧠")

            # 3. SAVE DATA UPDATES
            save_df = edited_df.drop(columns=['Create Rule', 'Include Amt'], errors='ignore')
            
            existing_rows = save_df[save_df['id'].notna()].copy()
            new_rows = save_df[save_df['id'].isna()].copy()
            
            if not existing_rows.empty:
                upsert_expenses(existing_rows)
            
            if not new_rows.empty:
                insert_expenses(new_rows)
            
            st.success("✅ Changes Saved!")
            st.rerun()

else:
    st.info("👋 Upload a file or Paste Text in the sidebar to begin!")
