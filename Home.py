import streamlit as st


st.title("Lance Workspace")
st.caption("A local Streamlit workspace for Lance, Flexar, and contract tools.")

st.subheader("Lance")

st.page_link("Lance/Tender/Tender.py", label="TenderBoard Scraper", icon=":material/search:")
st.page_link("Lance/Sesami/Sesami.py", label="Sesami Scraper", icon=":material/business_center:")
st.page_link("Lance/Recruitment_Tracker.py", label="Recruitment Tracker", icon=":material/groups:")
st.page_link("Lance/Converter/Converter.py", label="PDF to Word Converter", icon=":material/transform:")
st.page_link("Lance/whatsapp/WhatsApp.py", label="WhatsApp Monitor", icon=":material/chat:")

st.subheader("Flexar")

st.page_link("Flexar/BlueSG/Vehicle_Route_Optimiser.py", label="Vehicle Route Optimiser", icon=":material/route:")
st.page_link("Flexar/BlueSG/Route_Map_Viewer.py", label="Route Map Viewer", icon=":material/map:")
st.page_link("Flexar/whatsapp_request_processor/app.py", label="WhatsApp Request Processor", icon=":material/forum:")

st.subheader("Contracts")

st.page_link("Contracts/pages/CFS_Generator.py", label="CFS Contract Generator", icon=":material/description:")
st.page_link("Contracts/pages/LOA_Generator.py", label="Letter of Appointment", icon=":material/assignment:")
st.page_link("Contracts/pages/Service_Agreement_Generator.py", label="Service Agreement", icon=":material/contract:")

st.subheader("HR")

st.page_link("HR/RDL/app.py", label="RDL Management Studio", icon=":material/edit_document:")

st.divider()

st.write("Add new project pages as separate folders, then register them in `app.py`.")
