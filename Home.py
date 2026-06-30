import streamlit as st


st.title("Lance Workspace")
st.caption("A local Streamlit workspace for TenderBoard, Sesami, and future tools.")

st.subheader("Projects")

st.page_link("Tender/Tender.py", label="TenderBoard Scraper", icon=":material/search:")
st.page_link("Sesami/Sesami.py", label="Sesami Scraper", icon=":material/business_center:")
st.page_link("pages/Recruitment_Tracker.py", label="Recruitment Tracker", icon=":material/groups:")
st.page_link("Converter/Converter.py", label="PDF to Word Converter", icon=":material/transform:")
st.page_link("whatsapp/WhatsApp.py", label="WhatsApp Monitor", icon=":material/chat:")
st.page_link("BlueSG/Vehicle_Route_Optimiser.py", label="Vehicle Route Optimiser", icon=":material/route:")

st.divider()

st.write("Add new project pages as separate folders, then register them in `app.py`.")
