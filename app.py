import streamlit as st


st.set_page_config(page_title="Lance Workspace", layout="wide")

home = st.Page("Home.py", title="Home", icon=":material/home:")
tender = st.Page("Lance/Tender/Tender.py", title="TenderBoard", icon=":material/search:")
sesami = st.Page("Lance/Sesami/Sesami.py", title="Sesami", icon=":material/business_center:")
recruitment = st.Page(
    "Lance/Recruitment_Tracker.py",
    title="Recruitment Tracker",
    icon=":material/groups:",
)
converter = st.Page("Lance/Converter/Converter.py", title="Converter", icon=":material/transform:")
whatsapp = st.Page("Lance/whatsapp/WhatsApp.py", title="WhatsApp Monitor", icon=":material/chat:")
bluesg = st.Page(
    "Flexar/BlueSG/Vehicle_Route_Optimiser.py",
    title="Vehicle Route Optimiser",
    icon=":material/route:",
)
whatsapp_request_processor = st.Page(
    "Flexar/whatsapp_request_processor/app.py",
    title="WhatsApp Request Processor",
    icon=":material/forum:",
    url_path="whatsapp-request-processor",
)
cfs_generator = st.Page(
    "Contracts/pages/CFS_Generator.py",
    title="CFS Contract Generator",
    icon=":material/description:",
)
loa_generator = st.Page(
    "Contracts/pages/LOA_Generator.py",
    title="Letter of Appointment",
    icon=":material/assignment:",
)
service_agreement_generator = st.Page(
    "Contracts/pages/Service_Agreement_Generator.py",
    title="Service Agreement",
    icon=":material/contract:",
)
rdl_management_studio = st.Page(
    "HR/RDL/app.py",
    title="RDL Management Studio",
    icon=":material/edit_document:",
)

pg = st.navigation(
    {
        "Home": [home],
        "Lance": [tender, sesami, recruitment, converter, whatsapp],
        "Flexar": [bluesg, whatsapp_request_processor],
        "Contracts": [cfs_generator, loa_generator, service_agreement_generator],
        "HR": [rdl_management_studio],
    }
)

pg.run()
