import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client
from streamlit_cookies_controller import CookieController
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

COOKIE_NAME = "expense_tracker_auth"
COOKIE_EXPIRY_DAYS = 30

st.set_page_config(page_title="Cloud Expense Tracker", layout="wide", page_icon="💳")

controller = CookieController()

# ============================================
# 1. AUTHENTICATION WITH COOKIES
# ============================================
def check_password():
    try:
        saved_cookie = controller.get(COOKIE_NAME)
    except:
        saved_cookie = None
    
    if saved_cookie and "password_correct" not in st.session_state:
        try:
            saved_user, saved_pass = saved_cookie.split(":", 1)
            if "users" in st.secrets and saved_user in st.secrets["users"]:
                if st.secrets["users"][saved_user] == saved_pass:
                    st.session_state["password_correct"] = True
                    st.session_state["current_user"] = saved_user
                    return True
        except:
            try:
                controller.remove(COOKIE_NAME)
            except:
                pass
    
    def password_entered():
        user = st.session_state["username"].strip()
        password = st.session_state["password"].strip()
        remember = st.session_state.get("remember_me", False)
        
        if "users" in st.secrets and user in st.secrets["users"] and st.secrets["users"][user] == password:
            st.session_state["password_correct"] = True
            st.session_state["current_user"] = user
            
            if remember:
                try:
                    controller.set(COOKIE_NAME, f"{user}:{password}", max_age=COOKIE_EXPIRY_DAYS * 24 * 60 * 60)
                except:
                    pass
            
            if "password" in st.session_state:
                del st.session_state["password"]
            if "username" in st.session_state:
                del st.session_state["username"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.title("🔒 Login")
        st.text_input("Username", key="username")
        st.text_input("Password", type="password", key="password")
        st.checkbox("Remember me for 30 days", key="remember_me")
        st.button("Login", on_click=password_entered)
        return False
    elif not st.session_state["password_correct"]:
        st.title("🔒 Login")
        st.text_input("Username", key="username")
        st.text_input("Password", type="password", key="password")
        st.checkbox("Remember me for 30 days", key="remember_me")
        st.button("Login", on_click=password_entered)
        st.error("😕 User not found or password incorrect.")
        return False
    else:
        return True

if not check_password():
    st.stop()

# ============================================
# 1.5 LICENSE CHECK
# ============================================
def check_license():
    user = st.session_state["current_user"]
    
    if "licenses" not in st.secrets:
        st.error("⚠️ No license configuration found. Contact admin.")
        return False
    
    account_key = f"{user}_account"
    expiry_key = f"{user}_expiry"
    
    if account_key not in st.secrets["licenses"]:
        st.error(f"⚠️ No license found for user '{user}'. Contact admin.")
        return False
    
    user_account = st.secrets["licenses"][account_key]
    
    if expiry_key not in st.secrets["licenses"]:
        st.error(f"⚠️ No expiry date configured for user '{user}'. Contact admin.")
        return False
    
    expiry_str = st.secrets["licenses"][expiry_key]
    
    try:
        expiry_date = datetime.datetime.strptime(expiry_str, "%Y-%m-%d").date()
    except ValueError:
        st.error("⚠️ Invalid expiry date format. Contact admin.")
        return False
    
    today = datetime.date.today()
    
    if today > expiry_date:
        st.title("🔒 License Expired")
        st.error(f"⚠️ **Your license expired on {expiry_date.strftime('%B %d, %Y')}**\n\nAccount: `{user_account}`\n\nPlease contact support to renew.")
        return False
    
    days_left = (expiry_date - today).days
    if days_left <= 7:
        st.error(f"🚨 Your license expires in **{days_left} days**! Renew immediately.")
    elif days_left <= 30:
        st.warning(f"⏰ Your license expires in **{days_left} days** ({expiry_date.strftime('%b %d, %Y')}). Please renew soon!")
    
    st.session_state["user_account"] = user_account
    st.session_state["license_expiry"] = expiry_date
    
    return True

if not check_license():
    st.stop()

# ============================================
# 2. SUPABASE CONNECTION
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
    st.error(f"⚠️ No database configured for '{current_user}'.")
    st.stop()

@st.cache_resource
def get_supabase_client(url, key, user):
    """Create Supabase client. User param ensures cache is per-user."""
    return create_client(url, key)

sb = get_supabase_client(sb_url, sb_key, current_user)

# ============================================
# 3. DATA ACCESS FUNCTIONS
# ============================================
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
    df_save = df.rename(columns=EXP_COLS_REV)
    if 'id' in df_save.columns:
        df_save = df_save.drop(columns=['id'])
    valid_cols = list(EXP_COLS_REV.values())
    df_save = df_save[[c for c in df_save.columns if c in valid_cols]]
    records = prepare_records(df_save)
    if records:
        sb.table("expenses").insert(records).execute()

def upsert_expenses(df):
    df_save = df.rename(columns=EXP_COLS_REV)
    valid_cols = ['id'] + list(EXP_COLS_REV.values())
    df_save = df_save[[c for c in df_save.columns if c in valid_cols]]
    df_save['id'] = df_save['id'].astype(int)
    records = prepare_records(df_save)
    if records:
        sb.table("expenses").upsert(records).execute()

def delete_expenses(ids):
    for id_val in ids:
        sb.table("expenses").delete().eq("id", int(id_val)).execute()

def move_to_trash(df):
    df_save = df.copy()
    rename_map = {col: EXP_COLS_REV[col] for col in df_save.columns if col in EXP_COLS_REV}
    df_save = df_save.rename(columns=rename_map)
    
    if 'id' in df_save.columns:
        df_save['original_id'] = df_save['id']
        df_save = df_save.drop(columns=['id'])
    
    cols_to_remove = ['Delete', 'delete', 'Create Rule', 'create rule', 'Include Amt', 'include amt']
    for col in cols_to_remove:
        if col in df_save.columns:
            df_save = df_save.drop(columns=[col])
    
    valid_cols = ['original_id', 'date', 'description', 'amount', 'name', 'category', 'subcategory', 'source', 'person', 'locked']
    df_save = df_save[[c for c in df_save.columns if c.lower() in valid_cols]]
    
    records = prepare_records(df_save)
    if records:
        sb.table("deleted_expenses").insert(records).execute()

def load_trash():
    try:
        resp = sb.table("deleted_expenses").select("*").order("deleted_at", desc=True).execute()
        if resp.data:
            df = pd.DataFrame(resp.data)
            col_mapping = {
                'date': 'Date', 'description': 'Description', 'amount': 'Amount',
                'name': 'Name', 'category': 'Category', 'subcategory': 'SubCategory',
                'source': 'Source', 'person': 'Person', 'locked': 'Locked',
                'deleted_at': 'Deleted At', 'original_id': 'Original ID'
            }
            df = df.rename(columns=col_mapping)
            return df
        return pd.DataFrame()
    except:
        return pd.DataFrame()

def restore_from_trash(ids):
    restored_count = 0
    for trash_id in ids:
        try:
            resp = sb.table("deleted_expenses").select("*").eq("id", int(trash_id)).execute()
            if resp.data:
                item = resp.data[0]
                restore_item = {k: v for k, v in item.items() if k not in ['id', 'original_id', 'deleted_at']}
                sb.table("expenses").insert(restore_item).execute()
                sb.table("deleted_expenses").delete().eq("id", int(trash_id)).execute()
                restored_count += 1
        except Exception as e:
            st.error(f"Error restoring item {trash_id}: {e}")
    return restored_count

def empty_trash():
    try:
        sb.table("deleted_expenses").delete().gte("id", 0).execute()
    except Exception as e:
        st.error(f"Error emptying trash: {e}")

def load_list(table_name):
    try:
        resp = sb.table(table_name).select("name").execute()
        if resp.data:
            return sorted([r['name'] for r in resp.data if r.get('name')])
        return []
    except Exception as e:
        st.error(f"⚠️ Failed to load {table_name}: {e}")
        return None

def save_list(table_name, items):
    try:
        sb.table(table_name).delete().gte("id", 0).execute()
        if items:
            sb.table(table_name).insert([{"name": item} for item in items if item]).execute()
    except Exception as e:
        st.error(f"Error saving {table_name}: {e}")

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
    df_save = new_rules_df.rename(columns=RULES_COLS_REV)
    if 'id' in df_save.columns:
        df_save = df_save.drop(columns=['id'])
    valid_cols = list(RULES_COLS_REV.values())
    df_save = df_save[[c for c in df_save.columns if c in valid_cols]]
    records = prepare_records(df_save)
    if records:
        sb.table("rules").upsert(records, on_conflict="keyword").execute()

def get_match(description, amount, rules_df):
    desc = str(description).lower()
    if rules_df.empty:
        return None, None, None, None
    
    rules_sorted = rules_df.copy()
    rules_sorted['_kw_len'] = rules_sorted['Keyword'].str.len()
    rules_sorted = rules_sorted.sort_values('_kw_len', ascending=False)
    
    for _, row in rules_sorted.iterrows():
        if str(row['Keyword']).lower() in desc:
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
    
    is_fresh_db = df_history.empty or len(df_history) == 0
    
    if loaded_cats is None:
        loaded_cats = st.session_state.get('categories', sorted(DEFAULT_CATEGORIES))
    elif not loaded_cats:
        if is_fresh_db:
            save_list("categories", DEFAULT_CATEGORIES)
            loaded_cats = sorted(DEFAULT_CATEGORIES)
        else:
            loaded_cats = st.session_state.get('categories', sorted(DEFAULT_CATEGORIES))
    
    if loaded_subcats is None:
        loaded_subcats = st.session_state.get('subcategories', sorted(DEFAULT_SUBCATS))
    elif not loaded_subcats:
        if is_fresh_db:
            save_list("subcategories", DEFAULT_SUBCATS)
            loaded_subcats = sorted(DEFAULT_SUBCATS)
        else:
            loaded_subcats = st.session_state.get('subcategories', sorted(DEFAULT_SUBCATS))
    
    if loaded_people is None:
        loaded_people = st.session_state.get('people', sorted(DEFAULT_PEOPLE))
    elif not loaded_people:
        if is_fresh_db:
            save_list("people", DEFAULT_PEOPLE)
            loaded_people = sorted(DEFAULT_PEOPLE)
        else:
            loaded_people = st.session_state.get('people', sorted(DEFAULT_PEOPLE))
    
    if df_rules.empty:
        seed_rules = [{"Keyword": k, "Name": v["name"], "Category": v["category"], "SubCategory": v["subcategory"], "Person": v["person"], "Amount": None} for k, v in DEFAULT_RULES.items()]
        df_rules = pd.DataFrame(seed_rules)
        save_rules_full(df_rules)
        df_rules = load_rules()
except Exception as e:
    st.error(f"Error connecting to database: {e}")
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
# SIDEBAR
# ============================================
st.sidebar.header("🔘 Filters")

if not df_history.empty:
    df_history = df_history.dropna(subset=['Date'])

if not df_history.empty:
    min_date_avail = df_history['Date'].min().date()
    max_date_avail = df_history['Date'].max().date()
    start_date, end_date = st.sidebar.date_input("Period", [min_date_avail, max_date_avail])
    
    search_field = st.sidebar.radio("Search in:", ["Name", "Description", "Both"], horizontal=True, index=2)
    search_term = st.sidebar.text_input("Search", placeholder="e.g. Starbucks, Uber")

    data_people = df_history['Person'].dropna().unique().tolist()
    available_people = sorted(list(set(st.session_state['people'] + data_people)))
    
    data_cats = df_history['Category'].dropna().unique().tolist()
    available_cats = sorted(list(set(st.session_state['categories'] + data_cats)))
    
    data_subs = [x for x in df_history['SubCategory'].dropna().unique().tolist() if x != '']
    available_subcats = sorted(list(set(st.session_state['subcategories'] + data_subs)))
    
    all_sources_list = sorted(df_history['Source'].dropna().unique().tolist())

    # Initialize filter selections in session state
    if 'ppl_selection' not in st.session_state:
        st.session_state['ppl_selection'] = available_people.copy()
    if 'cat_selection' not in st.session_state:
        st.session_state['cat_selection'] = [c for c in available_cats if c != 'Transfer/Payment']
    if 'sub_selection' not in st.session_state:
        st.session_state['sub_selection'] = available_subcats.copy()
    if 'src_selection' not in st.session_state:
        st.session_state['src_selection'] = all_sources_list.copy()

    # Filter People - Compact Layout with working All button
    col_ppl_label, col_ppl_btn = st.sidebar.columns([3, 1])
    col_ppl_label.markdown("**People**")
    if col_ppl_btn.button("All", key="btn_all_ppl", use_container_width=True):
        st.session_state['ppl_selection'] = available_people.copy()
    
    # Validate current selection against available options
    current_ppl = st.session_state.get('ppl_selection', [])
    valid_ppl = [p for p in current_ppl if p in available_people]
    if not valid_ppl:
        valid_ppl = available_people.copy()
    
    selected_people = st.sidebar.multiselect(
        "People", 
        options=available_people, 
        default=valid_ppl, 
        key="ppl_filter", 
        label_visibility="collapsed"
    )
    st.session_state['ppl_selection'] = selected_people

    # Filter Categories - Compact Layout
    col_cat_label, col_cat_btn = st.sidebar.columns([3, 1])
    col_cat_label.markdown("**Categories**")
    if col_cat_btn.button("All", key="btn_all_cat", use_container_width=True):
        st.session_state['cat_selection'] = available_cats.copy()
    
    current_cats = st.session_state.get('cat_selection', [])
    valid_cats = [c for c in current_cats if c in available_cats]
    if not valid_cats:
        valid_cats = [c for c in available_cats if c != 'Transfer/Payment']
    
    selected_categories = st.sidebar.multiselect(
        "Categories", 
        options=available_cats, 
        default=valid_cats, 
        key="cat_filter", 
        label_visibility="collapsed"
    )
    st.session_state['cat_selection'] = selected_categories

    # Filter Sub-Categories - Compact Layout
    col_sub_label, col_sub_btn = st.sidebar.columns([3, 1])
    col_sub_label.markdown("**Sub-Categories**")
    if col_sub_btn.button("All", key="btn_all_sub", use_container_width=True):
        st.session_state['sub_selection'] = available_subcats.copy()
    
    current_subs = st.session_state.get('sub_selection', [])
    valid_subs = [s for s in current_subs if s in available_subcats]
    if not valid_subs:
        valid_subs = available_subcats.copy()
    
    selected_subcats = st.sidebar.multiselect(
        "Sub-Categories", 
        options=available_subcats, 
        default=valid_subs, 
        key="sub_filter", 
        label_visibility="collapsed"
    )
    st.session_state['sub_selection'] = selected_subcats

    # Filter Source - Compact Layout
    col_src_label, col_src_btn = st.sidebar.columns([3, 1])
    col_src_label.markdown("**Source**")
    if col_src_btn.button("All", key="btn_all_src", use_container_width=True):
        st.session_state['src_selection'] = all_sources_list.copy()
    
    current_srcs = st.session_state.get('src_selection', [])
    valid_srcs = [s for s in current_srcs if s in all_sources_list]
    if not valid_srcs:
        valid_srcs = all_sources_list.copy()
    
    selected_sources = st.sidebar.multiselect(
        "Source", 
        options=all_sources_list, 
        default=valid_srcs, 
        key="src_filter", 
        label_visibility="collapsed"
    )
    st.session_state['src_selection'] = selected_sources

else:
    start_date, end_date = None, None
    selected_people, selected_categories, selected_subcats, selected_sources = [], [], [], []
    search_term, search_field = "", "Both"
    available_cats = st.session_state['categories']
    available_subcats = st.session_state['subcategories']
    available_people = st.session_state['people']

st.sidebar.markdown("---")

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

    edited_rules = st.data_editor(rules_display, num_rows="dynamic", use_container_width=True, hide_index=True, key="rule_editor",
        column_config={
            "Keyword": st.column_config.TextColumn("Keyword"),
            "Name": st.column_config.TextColumn("Name"),
            "Category": st.column_config.SelectboxColumn("Category", options=st.session_state['categories'], required=True),
            "SubCategory": st.column_config.SelectboxColumn("SubCategory", options=st.session_state['subcategories']),
            "Person": st.column_config.SelectboxColumn("Person", options=st.session_state['people'], required=True),
            "Amount": st.column_config.NumberColumn("Amount", format="%.2f")
        })
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
    new_amount = st.number_input("Exact Amount (optional)", value=None, step=0.01, key="teach_amt")
    
    if st.button("➕ Add Rule"):
        if new_keyword:
            new_rule_row = pd.DataFrame([{"Keyword": new_keyword, "Name": new_name, "Category": new_cat_rule, "SubCategory": new_sub_rule, "Person": new_person_rule, "Amount": new_amount}])
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
                    new_rules_list.append({"Keyword": desc_key, "Name": row.get('Name', '') if pd.notna(row.get('Name')) else '', "Category": row['Category'], "SubCategory": row.get('SubCategory', ''), "Person": row['Person'], "Amount": None})
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

with st.sidebar.expander("🗑️ Recycle Bin", expanded=False):
    trash_df = load_trash()
    if not trash_df.empty:
        trash_count = len(trash_df)
        st.warning(f"**{trash_count} items in trash**")
        trash_display = trash_df.copy()
        if 'Date' in trash_display.columns:
            trash_display['Date'] = pd.to_datetime(trash_display['Date'], errors='coerce').dt.date
        if 'Deleted At' in trash_display.columns:
            trash_display['Deleted At'] = pd.to_datetime(trash_display['Deleted At'], errors='coerce').dt.strftime('%b %d, %H:%M')
        trash_display['Restore'] = False
        display_trash_cols = ['id', 'Restore', 'Date', 'Name', 'Description', 'Amount', 'Category', 'Deleted At']
        trash_display = trash_display[[c for c in display_trash_cols if c in trash_display.columns]]
        edited_trash = st.data_editor(trash_display, column_config={"id": None, "Restore": st.column_config.CheckboxColumn("✅", width="small"), "Amount": st.column_config.NumberColumn("Amount", format="$%.2f")}, hide_index=True, use_container_width=True, height=200, key="trash_editor")
        selected_restore = edited_trash[edited_trash['Restore'] == True] if 'Restore' in edited_trash.columns else pd.DataFrame()
        restore_count = len(selected_restore)
        col_trash1, col_trash2 = st.columns(2)
        if restore_count > 0:
            if col_trash1.button(f"♻️ Restore ({restore_count})", use_container_width=True, key="btn_restore"):
                ids_to_restore = selected_restore['id'].dropna().tolist()
                restored = restore_from_trash(ids_to_restore)
                st.success(f"✅ Restored {restored} items!")
                st.rerun()
        else:
            col_trash1.button("♻️ Restore (0)", disabled=True, use_container_width=True, key="btn_restore_disabled")
        if col_trash2.button("🗑️ Empty Trash", use_container_width=True, key="btn_empty"):
            st.session_state['confirm_empty_trash'] = True
        if st.session_state.get('confirm_empty_trash', False):
            st.error(f"⚠️ Permanently delete all {trash_count} items?")
            col_c1, col_c2 = st.columns(2)
            if col_c1.button("✅ Yes, Empty", key="confirm_empty_yes"):
                empty_trash()
                st.session_state['confirm_empty_trash'] = False
                st.success("🗑️ Trash emptied!")
                st.rerun()
            if col_c2.button("❌ Cancel", key="confirm_empty_no"):
                st.session_state['confirm_empty_trash'] = False
                st.rerun()
    else:
        st.info("🗑️ Trash is empty")

st.sidebar.markdown("---")

# ============================================
# IMPORT DATA - FIXED VERSION
# ============================================
st.sidebar.header("📤 Import Data")
manual_source = st.sidebar.text_input("Source Name", placeholder="e.g. HSBC Credit", key="source_input")
input_method = st.sidebar.radio("Input Method:", ["Upload File", "Paste Text"])

# Initialize upload state
if 'upload_processed' not in st.session_state:
    st.session_state['upload_processed'] = False
if 'last_upload_name' not in st.session_state:
    st.session_state['last_upload_name'] = None

new_data = pd.DataFrame()

if input_method == "Upload File":
    uploaded_file = st.sidebar.file_uploader("Upload CSV/Excel", type=["csv", "xlsx"], key="file_uploader")
    
    if uploaded_file is not None:
        # Check if this is a new file or the same one already processed
        current_file_name = uploaded_file.name
        
        if st.session_state.get('last_upload_name') != current_file_name:
            # New file - reset processing flag
            st.session_state['upload_processed'] = False
            st.session_state['last_upload_name'] = current_file_name
        
        if not st.session_state['upload_processed']:
            try:
                if uploaded_file.name.endswith('.csv'):
                    new_data = pd.read_csv(uploaded_file)
                else:
                    new_data = pd.read_excel(uploaded_file)
                
                # Process the data
                if not new_data.empty:
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
                        new_data[amt_col] = new_data[amt_col].astype(str).str.upper().str.replace('CR','', regex=False).str.replace('DR','', regex=False).str.replace(',','', regex=False).str.replace('$','', regex=False)
                        new_data[amt_col] = pd.to_numeric(new_data[amt_col], errors='coerce')
                        file_source = new_data[src_col] if src_col else (manual_source if manual_source else "Uploaded")
                        
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
                        
                        # Apply rules
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
                        
                        # Check for duplicates
                        existing = load_expenses()
                        if not existing.empty:
                            existing['_key'] = existing['Date'].astype(str) + '|' + existing['Description'].astype(str) + '|' + existing['Amount'].astype(str)
                            clean_new_data['_key'] = clean_new_data['Date'].astype(str) + '|' + clean_new_data['Description'].astype(str) + '|' + clean_new_data['Amount'].astype(str)
                            truly_new = clean_new_data[~clean_new_data['_key'].isin(existing['_key'])].drop(columns=['_key'])
                        else:
                            truly_new = clean_new_data
                        
                        # Mark as processed BEFORE inserting
                        st.session_state['upload_processed'] = True
                        
                        if not truly_new.empty:
                            insert_expenses(truly_new)
                            st.sidebar.success(f"✅ Added {len(truly_new)} new transactions!")
                            st.rerun()
                        else:
                            st.sidebar.warning("⚠️ All transactions already exist.")
                    else:
                        st.sidebar.error("Headers missing (need Date, Description, Amount).")
            except Exception as e:
                st.sidebar.error(f"Error: {e}")
                st.session_state['upload_processed'] = True  # Prevent infinite loop on error

elif input_method == "Paste Text":
    # Reset upload state when switching to paste
    st.session_state['upload_processed'] = False
    st.session_state['last_upload_name'] = None
    
    pasted_text = st.sidebar.text_area("Paste CSV Data", height=150, key="paste_area")
    
    if st.sidebar.button("Process Pasted Data", key="process_paste_btn"):
        if pasted_text and pasted_text.strip():
            try:
                new_data = pd.read_csv(io.StringIO(pasted_text), sep=',')
                
                if not new_data.empty:
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
                        new_data[amt_col] = new_data[amt_col].astype(str).str.upper().str.replace('CR','', regex=False).str.replace('DR','', regex=False).str.replace(',','', regex=False).str.replace('$','', regex=False)
                        new_data[amt_col] = pd.to_numeric(new_data[amt_col], errors='coerce')
                        file_source = new_data[src_col] if src_col else (manual_source if manual_source else "Pasted")
                        
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
                        
                        # Apply rules
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
                        
                        # Check for duplicates
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
                            st.rerun()
                        else:
                            st.sidebar.warning("⚠️ All transactions already exist.")
                    else:
                        st.sidebar.error("Headers missing (need Date, Description, Amount).")
            except Exception as e:
                st.sidebar.error(f"Error: {e}")
        else:
            st.sidebar.warning("Please paste some data first.")

st.sidebar.markdown("---")

st.sidebar.header("⚙️ Settings")
font_choice = st.sidebar.select_slider("Aa Text Size", options=["Small", "Default", "Large"], value="Default")
font_size = "14px" if font_choice == "Small" else "20px" if font_choice == "Large" else "16px"
st.markdown(f"<style>html, body, [class*='css'] {{ font-size: {font_size} !important; }}</style>", unsafe_allow_html=True)

st.sidebar.markdown("---")
st.sidebar.header("📄 License")
if "user_account" in st.session_state:
    st.sidebar.text(f"Account: {st.session_state['user_account']}")
if "license_expiry" in st.session_state:
    expiry = st.session_state['license_expiry']
    days_left = (expiry - datetime.date.today()).days
    st.sidebar.text(f"Expires: {expiry.strftime('%b %d, %Y')}")
    st.sidebar.text(f"Days left: {days_left}")

st.sidebar.markdown("---")
st.sidebar.header("📌 Connection")
st.sidebar.success("✅ Connected to Supabase")
st.sidebar.caption(f"Project: ...{sb_url[-25:]}")

st.sidebar.markdown("---")
if st.sidebar.button("🚪 Logout"):
    try:
        controller.remove(COOKIE_NAME)
    except:
        pass
    
    # ADD THIS LINE - Clear the cached Supabase client
    get_supabase_client.clear()
    
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

    mask = (df_history['Date'].dt.date >= start_date) & (df_history['Date'].dt.date <= end_date) & (df_history['Category'].isin(selected_categories)) & (df_history['SubCategory'].isin(selected_subcats) | (df_history['SubCategory'] == '')) & (df_history['Person'].isin(selected_people)) & (df_history['Source'].isin(selected_sources))
    
    if search_term:
        keywords = [k.strip() for k in search_term.replace(',', ' ').split() if k.strip()]
        if keywords:
            pattern = '|'.join(keywords)
            if search_field == "Name":
                mask = mask & df_history['Name'].astype(str).str.contains(pattern, case=False, na=False)
            elif search_field == "Description":
                mask = mask & df_history['Description'].astype(str).str.contains(pattern, case=False, na=False)
            else:
                mask = mask & (df_history['Name'].astype(str).str.contains(pattern, case=False, na=False) | df_history['Description'].astype(str).str.contains(pattern, case=False, na=False))

    filtered_df = df_history.loc[mask].copy()

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
            cat_display = cat_group.sort_values(by='AbsAmount', ascending=False)
            cat_display['Total'] = cat_display['AbsAmount'].apply(lambda x: f"${x:,.2f}")
            st.dataframe(cat_display[['Category', 'Total']], hide_index=True, use_container_width=True)

    with col_main_2:
        st.subheader("Spending by Person")
        p_pie = p_group[p_group['AbsAmount'] > 0]
        if not p_pie.empty:
            fig2 = px.pie(p_pie, values='AbsAmount', names='Person', hole=0.4, color_discrete_sequence=px.colors.qualitative.Set3)
            st.plotly_chart(fig2, use_container_width=True)
            p_display = p_group.sort_values(by='AbsAmount', ascending=False)
            p_display['Total'] = p_display['AbsAmount'].apply(lambda x: f"${x:,.2f}")
            st.dataframe(p_display[['Person', 'Total']], hide_index=True, use_container_width=True)

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
            st.info("👈 Click a Category on the left to see details.")

    st.markdown("---")
    st.subheader("📝 Transaction Editor")

    # === QUICK ADD CATEGORY ===
    with st.expander("➕ Quick Add Category/SubCategory", expanded=False):
        col_qa1, col_qa2, col_qa3 = st.columns([2, 2, 1])
    
        with col_qa1:
            new_cat_quick = st.text_input("New Category:", placeholder="e.g. Healthcare", key="quick_cat")
        with col_qa2:
            new_sub_quick = st.text_input("New Sub-Category:", placeholder="e.g. Pharmacy", key="quick_sub")
        with col_qa3:
            st.markdown("<br>", unsafe_allow_html=True)  # Spacing
            if st.button("➕ Add", key="quick_add_btn", use_container_width=True):
                added = []
                if new_cat_quick and new_cat_quick.strip():
                    cat_clean = new_cat_quick.strip()
                    if cat_clean not in st.session_state['categories']:
                        st.session_state['categories'].append(cat_clean)
                        st.session_state['categories'].sort()
                        save_list("categories", st.session_state['categories'])
                        added.append(f"Category: {cat_clean}")
            
                if new_sub_quick and new_sub_quick.strip():
                    sub_clean = new_sub_quick.strip()
                    if sub_clean not in st.session_state['subcategories']:
                        st.session_state['subcategories'].append(sub_clean)
                        st.session_state['subcategories'].sort()
                        save_list("subcategories", st.session_state['subcategories'])
                        added.append(f"Sub-Category: {sub_clean}")
            
                if added:
                    st.success(f"✅ Added: {', '.join(added)}")
                    st.rerun()
                else:
                    st.warning("Nothing new to add (already exists or empty)")

    # Show current options for reference
    with st.expander("📋 Current Categories & Sub-Categories", expanded=False):
        col_list1, col_list2 = st.columns(2)
        with col_list1:
            st.markdown("**Categories:**")
            st.caption(", ".join(sorted(available_cats)))
        with col_list2:
            st.markdown("**Sub-Categories:**")
            st.caption(", ".join(sorted(available_subcats)))
# === END OF QUICK ADD CATEGORY === #
    
    sort_option = st.selectbox("Sort By:", ["Date (Newest)", "Date (Oldest)", "Amount (Lowest first - Big Spends)", "Amount (Highest first - Income)", "Name (A-Z)", "Name (Z-A)", "Description (A-Z)", "Description (Z-A)", "Native (Click Headers to Sort)"])

    # Bulk Actions - Multi-Select Style
    with st.expander("⚡ Bulk Actions", expanded=False):
        st.markdown("**Select actions and click Apply:**")
        
        col_b1, col_b2, col_b3, col_b4 = st.columns(4)
        
        with col_b1:
            st.markdown("**🔒 Lock**")
            lock_all = st.checkbox("Lock All", key="bulk_lock_all")
            unlock_all = st.checkbox("Unlock All", key="bulk_unlock_all")
        
        with col_b2:
            st.markdown("**💲 Amount**")
            amt_all = st.checkbox("Include All", key="bulk_amt_all")
            amt_clear = st.checkbox("Clear All", key="bulk_amt_clear")
        
        with col_b3:
            st.markdown("**➕ Rules**")
            rule_all = st.checkbox("Select All", key="bulk_rule_all")
            rule_clear = st.checkbox("Clear All", key="bulk_rule_clear")
        
        with col_b4:
            st.markdown("**🗑️ Delete**")
            del_all = st.checkbox("Select All", key="bulk_del_all")
            del_clear = st.checkbox("Clear All", key="bulk_del_clear")
        
        if st.button("▶️ Apply Selected Actions", use_container_width=True, type="primary"):
            if 'transaction_editor' in st.session_state:
                del st.session_state['transaction_editor']
            
            actions = []
            if lock_all:
                actions.append('select_lock')
            if unlock_all:
                actions.append('clear_lock')
            if amt_all:
                actions.append('select_amt')
            if amt_clear:
                actions.append('clear_amt')
            if rule_all:
                actions.append('select_rule')
            if rule_clear:
                actions.append('clear_rule')
            if del_all:
                actions.append('select_delete')
            if del_clear:
                actions.append('clear_delete')
            
            if actions:
                st.session_state['bulk_actions'] = actions
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
        filtered_df_display['Delete'] = False
        filtered_df_display['Create Rule'] = False
        filtered_df_display['Include Amt'] = False
        filtered_df_display['Locked'] = filtered_df_display['Locked'].fillna(False).astype(bool)
        if 'Name' not in filtered_df_display.columns:
            filtered_df_display['Name'] = ''

        # Apply bulk actions from session state (supports multiple)
        bulk_actions = st.session_state.get('bulk_actions', [])
        
        for bulk_action in bulk_actions:
            if bulk_action == 'select_delete':
                filtered_df_display.loc[filtered_df_display['Locked'] == False, 'Delete'] = True
            elif bulk_action == 'clear_delete':
                filtered_df_display['Delete'] = False
            elif bulk_action == 'select_lock':
                filtered_df_display['Locked'] = True
            elif bulk_action == 'clear_lock':
                filtered_df_display['Locked'] = False
            elif bulk_action == 'select_rule':
                filtered_df_display.loc[filtered_df_display['Locked'] == False, 'Create Rule'] = True
            elif bulk_action == 'clear_rule':
                filtered_df_display['Create Rule'] = False
            elif bulk_action == 'select_amt':
                filtered_df_display['Include Amt'] = True
            elif bulk_action == 'clear_amt':
                filtered_df_display['Include Amt'] = False

        # Column order: Lock, Date, Name, Description (moved next to Name), Amount, Category, SubCategory, Person, Source, Include Amt, Create Rule, Delete
        display_cols = ['id', 'Locked', 'Date', 'Name', 'Description', 'Amount', 'Category', 'SubCategory', 'Person', 'Source', 'Include Amt', 'Create Rule', 'Delete']
        filtered_df_display = filtered_df_display[[c for c in display_cols if c in filtered_df_display.columns]]

        edited_df = st.data_editor(
            filtered_df_display,
            column_order=['Locked', 'Date', 'Name', 'Description', 'Amount', 'Category', 'SubCategory', 'Person', 'Source', 'Include Amt', 'Create Rule', 'Delete'],
            column_config={
                "id": None,
                "Locked": st.column_config.CheckboxColumn("🔒", width="small"),
                "Date": st.column_config.DateColumn("Date"),
                "Name": st.column_config.TextColumn("Name"),
                "Description": st.column_config.TextColumn("Description"),
                "Amount": st.column_config.NumberColumn("Amount", format="$%.2f"),
                "Category": st.column_config.SelectboxColumn("Category", options=available_cats, required=True),
                "SubCategory": st.column_config.SelectboxColumn("Sub-Category", options=available_subcats),
                "Person": st.column_config.SelectboxColumn("Person", options=available_people, required=True),
                "Source": st.column_config.TextColumn("Source", disabled=True),
                "Include Amt": st.column_config.CheckboxColumn("💲", width="small"),
                "Create Rule": st.column_config.CheckboxColumn("➕", width="small"),
                "Delete": st.column_config.CheckboxColumn("🗑️", width="small")
            },
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
            height=500,
            key="transaction_editor"
        )

        rows_to_delete = edited_df[edited_df['Delete'] == True] if 'Delete' in edited_df.columns else pd.DataFrame()
        delete_count = len(rows_to_delete)

        st.markdown("---")
        col_action1, col_action2, col_action3 = st.columns([2, 1, 1])
        save_clicked = col_action1.button("💾 Save Changes & Create Rules", type="primary", use_container_width=True)
        
        if delete_count > 0:
            delete_clicked = col_action2.button(f"🗑️ Delete Selected ({delete_count})", type="secondary", use_container_width=True)
        else:
            delete_clicked = False
            col_action2.button("🗑️ Delete Selected (0)", disabled=True, use_container_width=True)

        if delete_clicked and delete_count > 0:
            st.session_state['rows_to_delete'] = rows_to_delete.copy()
            st.session_state['confirm_delete_selected'] = True
            st.rerun()

        if st.session_state.get('confirm_delete_selected', False):
            saved_rows = st.session_state.get('rows_to_delete', pd.DataFrame())
            saved_count = len(saved_rows) if saved_rows is not None and not saved_rows.empty else 0
            
            if saved_count > 0:
                st.warning(f"⚠️ Delete **{saved_count}** transactions? They will be moved to Recycle Bin.")
                col_confirm1, col_confirm2, col_confirm3 = st.columns([1, 1, 2])
                if col_confirm1.button("✅ Yes, Delete", key="confirm_del_yes", type="primary", use_container_width=True):
                    ids_to_delete = saved_rows['id'].dropna().tolist()
                    if ids_to_delete:
                        move_to_trash(saved_rows)
                        delete_expenses(ids_to_delete)
                        st.session_state['confirm_delete_selected'] = False
                        st.session_state['rows_to_delete'] = None
                        if 'transaction_editor' in st.session_state:
                            del st.session_state['transaction_editor']
                        if 'bulk_actions' in st.session_state:
                            del st.session_state['bulk_actions']
                        st.success(f"🗑️ Moved {len(ids_to_delete)} items to Recycle Bin!")
                        st.rerun()
                if col_confirm2.button("❌ Cancel", key="confirm_del_no", use_container_width=True):
                    st.session_state['confirm_delete_selected'] = False
                    st.session_state['rows_to_delete'] = None
                    st.rerun()
            else:
                st.session_state['confirm_delete_selected'] = False

        if save_clicked:
            rules_created = 0
            new_cats_added = False
            new_subs_added = False
            new_people_added = False
            rule_errors = []
            
            # === DETECT WHICH ROWS ACTUALLY CHANGED ===
            original_df = filtered_df_display.copy()
            
            for idx, row in edited_df.iterrows():
                if row.get('Delete', False):
                    continue
                
                # Check if this row was actually modified
                row_changed = False
                create_rule = row.get('Create Rule', False)
                
                # Find original row by id
                row_id = row.get('id')
                if row_id is not None and not pd.isna(row_id):
                    orig_matches = original_df[original_df['id'] == row_id]
                    if not orig_matches.empty:
                        orig_row = orig_matches.iloc[0]
                        if (row.get('Category') != orig_row.get('Category') or
                            row.get('SubCategory') != orig_row.get('SubCategory') or
                            row.get('Person') != orig_row.get('Person') or
                            row.get('Name') != orig_row.get('Name') or
                            row.get('Locked') != orig_row.get('Locked')):
                            row_changed = True
                    else:
                        row_changed = True
                else:
                    row_changed = True
                
                # Only auto-add if row changed OR creating a rule
                if row_changed or create_rule:
                    cat = row.get('Category')
                    sub = row.get('SubCategory', '')
                    person = row.get('Person', 'Family')
                    
                    if cat and not pd.isna(cat) and cat != '':
                        if cat not in st.session_state['categories']:
                            st.session_state['categories'].append(cat)
                            st.session_state['categories'].sort()
                            new_cats_added = True
                    
                    if sub and not pd.isna(sub) and sub != '':
                        if sub not in st.session_state['subcategories']:
                            st.session_state['subcategories'].append(sub)
                            st.session_state['subcategories'].sort()
                            new_subs_added = True
                    
                    if person and not pd.isna(person) and person != '':
                        if person not in st.session_state['people']:
                            st.session_state['people'].append(person)
                            st.session_state['people'].sort()
                            new_people_added = True
            
            # Save updated lists
            if new_cats_added:
                save_list("categories", st.session_state['categories'])
                st.toast("✅ New categories added!", icon="📂")
            if new_subs_added:
                save_list("subcategories", st.session_state['subcategories'])
                st.toast("✅ New sub-categories added!", icon="🏷️")
            if new_people_added:
                save_list("people", st.session_state['people'])
                st.toast("✅ New people added!", icon="👥")
            
            # === CREATE RULES (only for checked rows) ===
            for idx, row in edited_df.iterrows():
                if row.get('Delete', False):
                    continue
                
                if row.get('Create Rule', False):
                    desc_text = str(row['Description']).lower().strip()
                    name = row.get('Name', '')
                    cat = row.get('Category')
                    sub = row.get('SubCategory', '')
                    person = row.get('Person', 'Family')
                    
                    if not desc_text:
                        rule_errors.append("Empty description - skipped")
                        continue
                    
                    if cat is None or pd.isna(cat) or cat == '':
                        cat = 'Uncategorized'
                    
                    if name is None or pd.isna(name):
                        name = ''
                    if sub is None or pd.isna(sub):
                        sub = ''
                    if person is None or pd.isna(person) or person == '':
                        person = 'Family'
                    
                    rule_amount = row['Amount'] if row.get('Include Amt', False) else None
                    
                    try:
                        new_rule = pd.DataFrame([{
                            "Keyword": str(desc_text),
                            "Name": str(name),
                            "Category": str(cat),
                            "SubCategory": str(sub),
                            "Person": str(person),
                            "Amount": rule_amount
                        }])
                        add_rules(new_rule)
                        rules_created += 1
                        edited_df.at[idx, 'Create Rule'] = False
                        edited_df.at[idx, 'Include Amt'] = False
                        edited_df.at[idx, 'Locked'] = True
                    except Exception as e:
                        rule_errors.append(f"'{desc_text[:30]}': {str(e)}")
            
            if rule_errors:
                st.error(f"⚠️ {len(rule_errors)} rule(s) failed:")
                for err in rule_errors[:5]:
                    st.warning(err)
            
            if rules_created > 0:
                st.toast(f"✅ Created {rules_created} new rules!", icon="🧠")
            
            # === SAVE ALL TRANSACTIONS ===
            try:
                save_df = edited_df[edited_df['Delete'] == False].drop(
                    columns=['Delete', 'Create Rule', 'Include Amt'], errors='ignore'
                )
                
                save_df['Category'] = save_df['Category'].fillna('Uncategorized').replace('', 'Uncategorized')
                save_df['SubCategory'] = save_df['SubCategory'].fillna('')
                save_df['Person'] = save_df['Person'].fillna('Family').replace('', 'Family')
                save_df['Name'] = save_df['Name'].fillna('')
                
                existing_rows = save_df[save_df['id'].notna()].copy()
                new_rows = save_df[save_df['id'].isna()].copy()
                
                if not existing_rows.empty:
                    upsert_expenses(existing_rows)
                if not new_rows.empty:
                    insert_expenses(new_rows)
                
                if 'transaction_editor' in st.session_state:
                    del st.session_state['transaction_editor']
                
                if 'bulk_actions' in st.session_state:
                    del st.session_state['bulk_actions']
                
                st.success("✅ Changes Saved!")
                st.rerun()
            
            except Exception as e:
                st.error(f"❌ Error saving transactions: {e}")
                st.exception(e)

else:
    st.info("👋 Upload a file or Paste Text in the sidebar to begin!")
