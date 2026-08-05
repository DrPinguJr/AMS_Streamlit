---
title: Workspace architecture and navigation
tags: [ams, architecture, streamlit]
---

# Workspace architecture and navigation

Back to [[00 Repository Index]].

## System shape

`app.py` is the full-workspace Streamlit entrypoint. It configures a wide page, calls the shared BlueSG password gate, builds grouped `st.Page` navigation, and runs the selected page.

```text
app.py
├─ Home.py
├─ Lance
│  ├─ TenderBoard
│  ├─ Sesami
│  ├─ Recruitment Tracker
│  ├─ Converter
│  └─ WhatsApp Monitor
├─ Flexar
│  ├─ BlueSG Vehicle Route Optimiser
│  ├─ BlueSG Route Planner
│  └─ WhatsApp Request Processor
├─ Contracts
│  ├─ CFS Contract Generator
│  ├─ Letter of Appointment
│  └─ Service Agreement
└─ HR
   ├─ HRIQ Report Tool
   └─ RDL Management Studio
```

`Home.py` repeats direct links to most tools. It omits the HRIQ Report Tool link even though `app.py` registers it under HR.

## Full-workspace route registration

| Group | Title | Page path | URL detail |
|---|---|---|---|
| Home | Home | `Home.py` | default Streamlit path |
| Lance | TenderBoard | `Lance/Tender/Tender.py` | — |
| Lance | Sesami | `Lance/Sesami/Sesami.py` | — |
| Lance | Recruitment Tracker | `Lance/Recruitment_Tracker.py` | — |
| Lance | Converter | `Lance/Converter/Converter.py` | — |
| Lance | WhatsApp Monitor | `Lance/whatsapp/WhatsApp.py` | — |
| Flexar | Vehicle Route Optimiser | `Flexar/BlueSG/pages/create_optimised_vehicle_routes_page.py` | — |
| Flexar | Route Planner | `Flexar/BlueSG/pages/review_map_and_manually_adjust_route_assignments_page.py` | — |
| Flexar | WhatsApp Request Processor | `Flexar/whatsapp_request_processor/app.py` | `whatsapp-request-processor` |
| Contracts | CFS Contract Generator | `Contracts/pages/CFS_Generator.py` | — |
| Contracts | Letter of Appointment | `Contracts/pages/LOA_Generator.py` | — |
| Contracts | Service Agreement | `Contracts/pages/Service_Agreement_Generator.py` | — |
| HR | HRIQ Report Tool | `Lance/HRIQ_Report_Tool/app.py` | `hriq-report-tool` |
| HR | RDL Management Studio | `HR/RDL/app.py` | — |

## BlueSG-only deployment

`Flexar/BlueSG/streamlit_app.py` adjusts `sys.path` and delegates to `cloud_streamlit_router.run_bluesg_cloud_app`. That router:

1. configures a wide BlueSG page;
2. enforces `APP_PASSWORD` access as needed;
3. runs deployment import/export smoke checks;
4. warns that Cloud storage is temporary;
5. exposes only `/optimise` and `/review` pages.

See [[BlueSG/08 Deployment Security Operations]].

## Shared technical characteristics

- Streamlit scripts rerun top-to-bottom; page-specific state is held in `st.session_state`.
- Many tools are Windows-first due to Word automation, Selenium/Chrome, SSPI, ODBC, filesystem paths, and launchers.
- Cloud-compatible BlueSG code is isolated by a dedicated minimal dependency file and preflight barrier.
- Root `.gitignore` treats credentials, live rider/staff/candidate data, generated workbooks, databases, caches, logs, browser profiles, and run artifacts as local runtime data.
- The repository mixes UI and domain modules. BlueSG, WhatsApp processing, contracts, and HRIQ have the clearest separation of UI from logic and the strongest automated tests.

## External systems

| System | Used by | Purpose |
|---|---|---|
| OneMap API | BlueSG | authentication, geocoding, driving/public-transport route costs |
| Streamlit Community Cloud | BlueSG/full app | optional hosted deployment |
| Microsoft Word COM | Contracts | DOCX-to-PDF conversion on Windows |
| Chrome/Selenium | Tender, Sesami, WhatsApp Monitor, HRIQ | browser automation and authenticated portal access |
| SSRS/HRIQ REST/portal | HRIQ tools | report discovery and RDL download |
| SQL Server/ODBC | HRIQ SQL workbench | read-only parameterized queries |
| FastAPI/Uvicorn | WhatsApp processor | webhook/simulator backend |
| SQLite | WhatsApp processor and HRIQ | persistent local state/index |
| ngrok | WhatsApp processor | optional HTTPS tunnel, never auto-registers WAAPI |

