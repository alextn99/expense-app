import streamlit as st
import pandas as pd
import plotly.express as px
from streamlit_gsheets import GSheetsConnection
import json

# --- CONFIGURATION ---
# Default fallbacks if the sheet is empty
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

st.set_page_config(page_title="Cloud Expense Tracker", layout="wide", page_icon="💳")

# --- 1. SETUP & AUTHENTICATION ---
def check_password():
    """Returns `True` if the user had the correct password."""
    def password_entered():
        # .strip() removes accidental spaces at the end
        user = st.session_state["username"].strip()
        password = st.session_state["password"].strip()
        
        # Check against the [users] section in Streamlit Secrets
        if "users" in st.secrets and user in st.secrets["users"] and st.secrets["users"][user] == password:
            st.session_state["password_correct"] = True
            st.session_state["current_user"] = user  # Remember who logged in
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

# --- 2. CONNECT TO GOOGLE SHEET ---
st.sidebar.header("📌 Connection")

if "sheet_url" not in st.session_state:
    st.session_state["sheet_url"] = ""

sheet_url = st.sidebar.text_input("Paste your Google Sheet Link:", value=st.session_state["sheet_url"])

if not sheet_url:
    st.warning("👈 Please paste your Google Sheet URL in the sidebar to begin.")
    st.stop()
else:
    st.session_state["sheet_url"] = sheet_url

# Establish Connection
conn = st.connection("gsheets", type=GSheetsConnection)

# --- 3. DATA LOADING FUNCTIONS ---
def load_data(tab_name, default_df=None):
    try:
        # ttl=0 ensures we don't cache old data forever
        df = conn.read(spreadsheet=sheet_url, worksheet=tab_name, ttl=0)
        return df
    except Exception:
        # If tab doesn't exist or is empty, return default
        return default_df if default_df is not None else pd.DataFrame()

def save_data(df, tab_name):
    conn.update(spreadsheet=sheet_url, worksheet=tab_name, data=df)

# Initialize Data Frames (Auto-Setup)
try:
    # 1. EXPENSES
    df_history = load_data("expenses")
    if df_history.empty: 
        df_history = pd.DataFrame(columns=['Date', 'Description', 'Amount', 'Category', 'SubCategory', 'Source', 'Person', 'Locked'])
        
    # 2. CATEGORIES
    df_cats = load_data("categories")
    if df_cats.empty: df_cats = pd.DataFrame(DEFAULT_CATEGORIES, columns=["Category Name"])

    # 3. SUBCATS
    df_subs = load_data("subcategories")
    if df_subs.empty: df_subs = pd.DataFrame(DEFAULT_SUBCATS, columns=["Sub-Category Name"])

    # 4. PEOPLE
    df_ppl = load_data("people")
    if df_ppl.empty: df_ppl = pd.DataFrame(DEFAULT_PEOPLE, columns=["Person Name"])

    # 5. RULES
    df_rules = load_data("rules")
    if df_rules.empty: df_rules = pd.DataFrame(columns=["Keyword", "Category", "SubCategory", "Person"])

except Exception as e:
    st.error(f"Error connecting to Sheet. Did you share it with the bot?\n\nDetails: {e}")
    st.stop()

# --- PRE-PROCESSING ---
if not df_history.empty:
    df_history['Date'] = pd.to_datetime(df_history['Date'], errors='coerce')
    df_history['SubCategory'] = df_history['SubCategory'].fillna('')
    if 'Locked' not in df_history.columns: df_history['Locked'] = False
    if 'Create Rule' not in df_history.columns: df_history['Create Rule'] = False

# --- SAFER LIST LOADING (Prevents Line 116 Error) ---
def get_column_safe(df, col_name):
    """Safely extracts a column as a list, returns empty if missing."""
    if not df.empty and col_name in df.columns:
        return sorted(df[col_name].dropna().unique().tolist())
    return []

# Load lists using safe function
available_cats = get_column_safe(df_cats, "Category Name")
if not available_cats: available_cats = sorted(DEFAULT_CATEGORIES)

available_subcats = get_column_safe(df_subs, "Sub-Category Name")
if not available_subcats: available_subcats = sorted(DEFAULT_SUBCATS)

available_people = get_column_safe(df_ppl, "Person Name")
if not available_people: available_people = sorted(DEFAULT_PEOPLE)

# --- 4. DASHBOARD LOGIC ---
current_user = st.session_state["current_user"]
st.title(f"💳 {current_user.title()}'s Cloud Expense Tracker")

# Initialize filtered_df to prevent NameError when df_history is empty
filtered_df = pd.DataFrame()

# ... [FILTERS SECTION] ...
if not df_history.empty:
    df_history = df_history.dropna(subset=['Date'])
    
    # Check if there's still data after dropping NaT dates
    if not df_history.empty:
        min_date = df_history['Date'].min().date()
        max_date = df_history['Date'].max().date()
        start_date, end_date = st.sidebar.date_input("Period", [min_date, max_date])
        
        # Simple Filters
        st.sidebar.markdown("---")
        selected_cats = st.sidebar.multiselect("Filter Category", available_cats, default=available_cats)
        
        # Filter Logic
        mask = (df_history['Date'].dt.date >= start_date) & \
               (df_history['Date'].dt.date <= end_date) & \
               (df_history['Category'].isin(selected_cats))
        
        filtered_df = df_history.loc[mask].copy()
        
        # Metrics
        if not filtered_df.empty:
            spend = filtered_df[filtered_df['Amount'] < 0]['Amount'].sum() * -1
            st.metric("Total Spend", f"${spend:,.2f}")
            
            # Pie Chart
            st.subheader("Spending by Category")
            cat_group = filtered_df.groupby('Category')['Amount'].sum().abs().reset_index()
            fig = px.pie(cat_group, values='Amount', names='Category', hole=0.4)
            st.plotly_chart(fig)

# ... [EDITOR SECTION] ...
st.divider()
st.subheader("📝 Transaction Editor")

if not filtered_df.empty:
    # Prepare display
    display_df = filtered_df.copy()
    display_df['Date'] = display_df['Date'].dt.date
    
    edited_df = st.data_editor(
        display_df,
        column_config={
            "Category": st.column_config.SelectboxColumn("Category", options=available_cats, required=True),
            "SubCategory": st.column_config.SelectboxColumn("Sub-Category", options=available_subcats),
            "Person": st.column_config.SelectboxColumn("Person", options=available_people),
            "Locked": st.column_config.CheckboxColumn("🔒"),
            "Create Rule": st.column_config.CheckboxColumn("➕ Rule")
        },
        hide_index=True,
        num_rows="dynamic",
        use_container_width=True
    )

    if st.button("💾 Save Changes to Google Sheet"):
        # 1. Update Rules
        new_rules = []
        for i, row in edited_df.iterrows():
            if row['Create Rule']:
                new_rules.append({
                    "Keyword": str(row['Description']).lower().strip(),
                    "Category": row['Category'],
                    "SubCategory": row['SubCategory'],
                    "Person": row['Person']
                })
        
        if new_rules:
            new_rules_df = pd.DataFrame(new_rules)
            updated_rules_df = pd.concat([df_rules, new_rules_df], ignore_index=True).drop_duplicates(subset=['Keyword'])
            save_data(updated_rules_df, "rules")
            st.toast(f"Saved {len(new_rules)} new rules!")

        # 2. Update Main Data - INDEX MATCHING
        deleted_indices = list(set(filtered_df.index) - set(edited_df.index))
        
        if deleted_indices:
            df_history = df_history.drop(deleted_indices)
            
        df_history.loc[edited_df.index] = edited_df
        df_history['Date'] = df_history['Date'].astype(str)
        
        save_data(df_history, "expenses")
        st.success("✅ Saved to Google Drive!")
        st.rerun()

else:
    st.info("No data found for this period.")

# --- 5. MIGRATION STATION (Restore Old Data) ---
st.sidebar.markdown("---")
with st.sidebar.expander("📂 MIGRATION STATION (Import Old Data)"):
    st.warning("Only use this to restore your old files to the Cloud!")

    # 1. Categories
    up_cats = st.file_uploader("Upload categories.json", type=['json'])
    if up_cats and st.button("Restore Categories"):
        data = json.load(up_cats)
        df = pd.DataFrame(data, columns=["Category Name"])
        save_data(df, "categories")
        st.toast("Categories Restored!")

    # 2. Sub-Categories
    up_subs = st.file_uploader("Upload subcategories.json", type=['json'])
    if up_subs and st.button("Restore Sub-Cats"):
        data = json.load(up_subs)
        df = pd.DataFrame(data, columns=["Sub-Category Name"])
        save_data(df, "subcategories")
        st.toast("Sub-Cats Restored!")

    # 3. People
    up_ppl = st.file_uploader("Upload people.json", type=['json'])
    if up_ppl and st.button("Restore People"):
        data = json.load(up_ppl)
        df = pd.DataFrame(data, columns=["Person Name"])
        save_data(df, "people")
        st.toast("People Restored!")

    # 4. Rules
    up_rules = st.file_uploader("Upload rules.json", type=['json'])
    if up_rules and st.button("Restore Rules"):
        data = json.load(up_rules)
        # Flatten dictionary to table
        rows = []
        for kw, details in data.items():
            if isinstance(details, dict):
                rows.append({"Keyword": kw, "Category": details.get("category"), "SubCategory": details.get("subcategory"), "Person": details.get("person")})
            else:
                rows.append({"Keyword": kw, "Category": details, "SubCategory": "", "Person": "Family"})
        
        df = pd.DataFrame(rows)
        save_data(df, "rules")
        st.toast("Rules Restored!")

    # 5. History
    up_csv = st.file_uploader("Upload my_expenses.csv", type=['csv'])
    if up_csv and st.button("Restore History"):
        df = pd.read_csv(up_csv)
        # Clean up
        if 'Create Rule' in df.columns: df = df.drop(columns=['Create Rule'])
        save_data(df, "expenses")
        st.success("History Restored!")
