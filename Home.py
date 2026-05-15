import streamlit as st


st.title("Lance Workspace")
st.caption("A local Streamlit workspace for TenderBoard scraping and future tools.")

st.subheader("Projects")

st.page_link("Tender/Tender.py", label="TenderBoard Scraper", icon=":material/search:")

st.divider()

st.write("Add new project pages as separate folders, then register them in `app.py`.")
