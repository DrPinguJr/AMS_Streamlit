import streamlit as st


st.set_page_config(page_title="Lance Workspace", layout="wide")

home = st.Page("Home.py", title="Home", icon=":material/home:")
tender = st.Page("Tender/Tender.py", title="TenderBoard", icon=":material/search:")

pages = st.navigation(
    {
        "Workspace": [home],
        "Projects": [tender],
    }
)

pages.run()
