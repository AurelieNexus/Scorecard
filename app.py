import streamlit as st
import pandas as pd
from io import BytesIO
 
# Imports for Google Search Console
import searchconsole
from apiclient import discovery
from google_auth_oauthlib.flow import Flow

# Import for OpenAI
import openai

###############################################################################
# Streamlit Page Configuration
###############################################################################

st.set_page_config(
    layout="centered", 
    page_title="GSC Keyword Categorizer", 
    page_icon="🔌📝"
)

###############################################################################
# Constants
###############################################################################

ROW_CAP = 25000
TOP_N_KEYWORDS = 50

###############################################################################
# Helper Functions
###############################################################################

def get_search_console_data(webproperty, search_type, selected_days, dimension, nested_dimension, nested_dimension_2):
    q = webproperty.query.search_type(search_type).range("today", days=selected_days).dimension(dimension)

    if nested_dimension != "none":
        q = q.dimension(nested_dimension)
    if nested_dimension_2 != "none":
        q = q.dimension(nested_dimension_2)

    q = q.limit(ROW_CAP)
    report = q.get().to_dataframe()
    return report

def categorize_with_openai(keyword, candidate_labels):
    prompt = (
        f"Given the following categories, classify the following keyword into one appropriate category "
        f"based on its meaning:\n\nKeyword: {keyword}\nCategories:\n- " +
        "\n- ".join(candidate_labels) +
        "\n\nProvide only the category, no other text."
    )
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=0
        )
        # Extract the response content
        content = response.choices[0].message.content.strip()
        return content
    except Exception as e:
        st.error(f"Error categorizing keyword '{keyword}': {e}")
        return None

@st.cache_data
def convert_df_to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False)
    processed_data = output.getvalue()
    return processed_data

###############################################################################
# Main App
###############################################################################

st.title("GSC Keyword Categorizer")

# Sidebar: Retrieve GSC credentials from Streamlit secrets
client_secret = st.secrets["installed"]["client_secret"]
client_id = st.secrets["installed"]["client_id"]
redirect_uri = st.secrets["installed"]["redirect_uris"][0]

# Initialize session state for OAuth tokens
if "gsc_token_input" not in st.session_state:
    st.session_state["gsc_token_input"] = ""
if "gsc_token_received" not in st.session_state:
    st.session_state["gsc_token_received"] = False

# Provide instructions for OAuth code retrieval
with st.sidebar:
    st.markdown(
        f"""
        1. [Connecte toi avec GSC](https://accounts.google.com/o/oauth2/auth?response_type=code&client_id={client_id}&redirect_uri={redirect_uri}&scope=https://www.googleapis.com/auth/webmasters.readonly&access_type=offline&prompt=consent)
        2. Copy the authorization code.
        3. Paste it below and press enter.
        """
    )

    # Manual entry for the OAuth authorization code
    auth_code_input = st.text_input("Enter Google OAuth Code", value="", key="auth_code")

    if auth_code_input:
        st.session_state["gsc_token_input"] = auth_code_input
        st.session_state["gsc_token_received"] = True
        st.success("Authorization code received.")

if st.session_state.gsc_token_received:
    try:
        # Fetch Account and Site List
        flow = Flow.from_client_config(
            {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uris": [redirect_uri],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://accounts.google.com/o/oauth2/token",
                }
            },
            scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
            redirect_uri=redirect_uri,
        )
        flow.fetch_token(code=st.session_state.gsc_token_input)
        credentials_fetched = flow.credentials
        service = discovery.build(
            serviceName="webmasters",
            version="v3",
            credentials=credentials_fetched,
            cache_discovery=False,
        )

        account = searchconsole.account.Account(service, credentials_fetched)
        site_list = service.sites().list().execute()
        first_value = list(site_list.values())[0]
        site_urls = [dicts.get("siteUrl") for dicts in first_value if dicts.get("siteUrl")]

        if site_urls:
            st.sidebar.info("✔️ GSC credentials OK!")

            # Data Fetching Form
            with st.form(key="gsc_data_form"):
                selected_site = st.selectbox("Select web property", site_urls)

                col1, col2, col3 = st.columns(3)

                with col1:
                    dimension = st.selectbox(
                        "Primary Dimension",
                        ("query",),
                        help="Primary dimension for the query.",
                    )
                with col2:
                    nested_dimension = st.selectbox(
                        "Nested Dimension",
                        ("none", "page", "date", "device", "searchAppearance", "country"),
                        help="Choose a nested dimension.",
                    )
                with col3:
                    nested_dimension_2 = st.selectbox(
                        "Second Nested Dimension",
                        ("none", "page", "date", "device", "searchAppearance", "country"),
                        help="Choose a second nested dimension.",
                    )

                search_type = st.selectbox(
                    "Search Type",
                    ("web", "news", "video", "googleNews", "image"),
                    help="Specify the search type.",
                )

                timescale = st.selectbox(
                    "Date Range",
                    ("Last 7 days", "Last 30 days", "Last 3 months", "Last 6 months", "Last 12 months"),
                    index=1,
                    help="Specify the date range.",
                )

                timescale_mapping = {
                    "Last 7 days": -7,
                    "Last 30 days": -30,
                    "Last 3 months": -91,
                    "Last 6 months": -182,
                    "Last 12 months": -365,
                }

                selected_days = timescale_mapping.get(timescale, -30)

                # Submit Button for Fetching GSC Data
                submit_gsc_data = st.form_submit_button(label="Fetch GSC Data")

                if submit_gsc_data:
                    webproperty = account[selected_site]
                    df = get_search_console_data(webproperty, search_type, selected_days, dimension, nested_dimension, nested_dimension_2)

                    if df.empty:
                        st.warning("🚨 No data available. Please refine your search criteria.")
                    else:
                        st.success(f"✅ Data fetched successfully! Total rows: {len(df)}")

                        # Select metric for top keywords
                        metric = st.selectbox(
                            "Select metric for top keywords",
                            options=["clicks", "impressions", "ctr", "position"],
                            help="Metric for selecting top keywords.",
                        )

                        # Extract top keywords
                        if 'query' in df.columns:
                            top_keywords_df = (
                                df.groupby('query')[metric]
                                .sum()
                                .reset_index()
                                .sort_values(by=metric, ascending=False)
                                .head(TOP_N_KEYWORDS)
                            )
                            top_keywords = top_keywords_df['query'].tolist()
                            st.write(f"### Top {TOP_N_KEYWORDS} Keywords based on {metric.capitalize()}")
                            st.dataframe(top_keywords_df)
                        else:
                            st.warning("🚨 'query' dimension not found in data.")
    except Exception as e:
        st.error(f"An error occurred: {str(e)}")

if df is not None and 'query' in df.columns:
    st.markdown("---")
    st.subheader("Keyword Categorization using OpenAI")

    # Upload labels file
    label_file = st.file_uploader(
        "Upload your labels (TXT format)",
        type="txt",
        help="Each line in the file should be a separate category."
    )

    if label_file:
        candidate_labels = label_file.read().decode("utf-8").splitlines()
        candidate_labels = [label.strip() for label in candidate_labels if label.strip()]

        if not candidate_labels:
            st.warning("🚨 The candidate labels file is empty.")
        else:
            st.success(f"Labels loaded: {', '.join(candidate_labels)}")

            categorized_results = []
            progress_bar = st.progress(0)

            for idx, keyword_row in top_keywords_df.iterrows():
                category = categorize_with_openai(keyword_row['query'], candidate_labels)
                if category:
                    categorized_results.append({
                        'Keyword': keyword_row['query'],
                        'Clicks': keyword_row[metric],
                        'Category': category
                    })
                progress_bar.progress((idx + 1) / len(top_keywords_df))

            # Convert results to DataFrame
            categorized_df = pd.DataFrame(categorized_results)
            st.success("✅ Keyword categorization completed!")

            # Display results
            st.write("### Categorization Results")
            st.dataframe(categorized_df)

            # Provide Excel download
            st.download_button(
                label="Download Results as Excel",
                data=convert_df_to_excel(categorized_df),
                file_name='classification_results.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
