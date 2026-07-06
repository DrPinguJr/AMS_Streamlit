import streamlit as st


st.set_page_config(page_title="Lance Workspace", layout="wide")

home = st.Page("Home.py", title="Home", icon=":material/home:")
tender = st.Page("Tender/Tender.py", title="TenderBoard", icon=":material/search:")
sesami = st.Page("Sesami/Sesami.py", title="Sesami", icon=":material/business_center:")
recruitment = st.Page(
    "pages/Recruitment_Tracker.py",
    title="Recruitment Tracker",
    icon=":material/groups:",
)
converter = st.Page("Converter/Converter.py", title="Converter", icon=":material/transform:")
whatsapp = st.Page("whatsapp/WhatsApp.py", title="WhatsApp Monitor", icon=":material/chat:")
bluesg = st.Page(
    "BlueSG/Vehicle_Route_Optimiser.py",
    title="Vehicle Route Optimiser",
    icon=":material/route:",
)
contract_generator = st.Page(
    "BlueSG/Contract_Generator.py",
    title="Contract Generator",
    icon=":material/description:",
)

pages = st.navigation(
    {
        "Workspace": [home],
        "Projects": [
            tender,
            sesami,
            recruitment,
            converter,
            whatsapp,
            bluesg,
            contract_generator,
        ],
    }
)

pages.run()
