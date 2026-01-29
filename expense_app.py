import streamlit as st
import pandas as pd
import plotly.express as px
from streamlit_gsheets import GSheetsConnection

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

st.set_page_config(page_title="Cloud Expense Tracker", layout="wide", page_icon="💳")

# --- 1. SETUP & AUTHENTICATION ---
# A simple gatekeeper so random internet people don't use your bot quota
def check_password():
    if st.secrets.get("PASSWORD") is None:
        return True # If no password set in secrets, allow entry (dev mode)
    
    def password_entered():
        if st.session_state["password"] == st.secrets["PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Enter App Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Enter App Password", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
    else:
        return True

if not check_password():
    st.stop()

# --- 2. CONNECT TO GOOGLE SHEET ---
st.sidebar.header("🔌 Connection")

# Allow user to paste their own sheet link
if "sheet_url" not in st.session_state:
    st.session_state["sheet_url"] = ""

sheet_url = st.sidebar.text_input("Paste your Google Sheet Link:", value=st.session_state["sheet_url"])

if not sheet_url:
    st.warning("👈 Please paste your Google Sheet URL in the sidebar to begin.")
    st.markdown("""
    ### How to set up your Sheet:
    1. Create a new Google Sheet.
    2. Click **Share** (Top Right).
    3. Invite this email as an **Editor**:  
       `streamlit-bot@YOUR-PROJECT-ID.iam.gserviceaccount.com` (Ask Alex for the exact email)
    4. Copy the link and paste it here.
    """)
    st.stop()
else:
    st.session_state["sheet_url"] = sheet_url

# Establish Connection
conn = st.connection("gsheets", type=GSheetsConnection)

# --- 3. DATA LOADING FUNCTIONS ---
def load_data(tab_name, default_df=None):
    try:
        df = conn.read(spreadsheet=sheet_url, worksheet=tab_name)
        return df
    except Exception:
        # If tab doesn't exist or is empty, return default
        return default_df if default_df is not None else pd.DataFrame()

def save_data(df, tab_name):
    conn.update(spreadsheet=sheet_url, worksheet=tab_name, data=df)

# Initialize Data Frames if Tabs are missing (Auto-Setup)
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
df_history['Date'] = pd.to_datetime(df_history['Date'], errors='coerce')
df_history['SubCategory'] = df_history['SubCategory'].fillna('')
if 'Locked' not in df_history.columns: df_history['Locked'] = False
if 'Create Rule' not in df_history.columns: df_history['Create Rule'] = False

# Convert Rules DF to Dictionary for fast lookup
rules_dict = {}
for i, row in df_rules.iterrows():
    rules_dict[str(row['Keyword'])] = {
        "category": row['Category'], 
        "subcategory": row['SubCategory'], 
        "person": row['Person']
    }

# Lists for Dropdowns
available_cats = sorted(df_cats["Category Name"].dropna().unique().tolist())
available_subcats = sorted(df_subs["Sub-Category Name"].dropna().unique().tolist())
available_people = sorted(df_ppl["Person Name"].dropna().unique().tolist())

# --- 4. DASHBOARD LOGIC (Same as before, updated for Cloud) ---
st.title("💳 Cloud Expense Tracker")

# ... [FILTERS SECTION] ...
if not df_history.empty:
    df_history = df_history.dropna(subset=['Date'])
    min_date = df_history['Date'].min().date()
    max_date = df_history['Date'].max().date()
    start_date, end_date = st.sidebar.date_input("Period", [min_date, max_date])
    
    # Simple Filters
    selected_cats = st.sidebar.multiselect("Filter Category", available_cats, default=available_cats)
    
    # Filter Logic
    mask = (df_history['Date'].dt.date >= start_date) & (df_history['Date'].dt.date <= end_date) & (df_history['Category'].isin(selected_cats))
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

        # 2. Update Main Data
        # We merge changes back to the main history based on Index (simple version)
        # For robustness in Cloud, we usually replace the whole dataset or match by ID.
        # Here we will assume the user filtered view matches what they want to save.
        
        # Map edits back to original DF using Index
        df_history.loc[edited_df.index] = edited_df
        
        # Convert Date back to string/datetime for GSheets
        df_history['Date'] = df_history['Date'].astype(str)
        
        save_data(df_history, "expenses")
        st.success("✅ Saved to Google Drive!")
        st.rerun()

else:
    st.info("No data found for this period.")

# --- 5. UPLOAD SECTION ---
with st.sidebar.expander("Upload New Data"):
    up_file = st.file_uploader("Upload CSV", type=['csv'])
    if up_file and st.button("Process Upload"):
        new_data = pd.read_csv(up_file)
        # (Add your cleaning logic here similar to previous versions)
        # For now, just append
        new_data['Locked'] = False
        new_data['Create Rule'] = False
        
        combined = pd.concat([df_history, new_data], ignore_index=True)
        save_data(combined, "expenses")
        st.success("Uploaded!")
        st.rerun()