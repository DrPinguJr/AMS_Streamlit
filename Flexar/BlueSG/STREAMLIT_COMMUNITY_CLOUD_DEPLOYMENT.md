# BlueSG Optimiser: Streamlit Community Cloud Deployment

This deployment runs only the BlueSG optimiser. The repository's root `app.py`
is for local use and includes Windows-only and local-service features. **Do not
select the root `app.py` when creating the Cloud app.**

## Deployment settings

Use these exact values in Streamlit Community Cloud:

| Setting | Value |
| --- | --- |
| Repository | `DrPinguJr/AMS_Streamlit` |
| Branch | `main` |
| Main file path | `Flexar/BlueSG/streamlit_app.py` |
| Python version | `3.12` |

The dedicated dependency file is
`Flexar/BlueSG/requirements.txt`. It should contain these pinned packages:

```text
streamlit==1.57.0
pandas==3.0.3
openpyxl==3.1.5
pydeck==0.9.2
```

No `packages.txt` file or Linux system package is needed for this BlueSG-only
deployment.

## Security requirement before launch

Do not launch this repository publicly with real staff or rider data.

The repository is currently public, and its Git history contains staff and
candidate personal information. Before a real launch, either:

1. make the GitHub repository private and restrict the Streamlit app to approved
   users; or
2. remove the personal information from the repository and rewrite the affected
   Git history before keeping it public.

Making only the Streamlit app private does not protect files that remain in a
public GitHub repository. Do not commit live rosters, resumes, candidate files,
credentials, generated workbooks, route caches, or run results.

The BlueSG Cloud entrypoint also requires a shared application password. Add a
long, unique value in Streamlit's Secrets editor. This password is an additional
gate; it does not replace private repository and app access controls.

## Required Streamlit secrets

Open the app's **Settings > Secrets** page and add:

```toml
APP_PASSWORD = "replace-with-a-long-unique-password"
ONEMAP_EMAIL = "your-onemap-account-email"
ONEMAP_PASSWORD = "your-onemap-account-password"
```

Do not add `.env` or `.streamlit/secrets.toml` to Git. Do not store a persistent
OneMap access token in the repository. The optimiser can obtain a fresh token
from the OneMap email and password.

## Local check before deployment

From the repository root, use a Python 3.12 environment:

```powershell
python --version
python -m pip install -r Flexar/BlueSG/requirements.txt
python -m streamlit run Flexar/BlueSG/streamlit_app.py
```

Confirm that:

- the login gate works;
- the optimiser and manual route-review pages both open;
- the confirmed-rider table accepts `Priority`, the legacy spelling `Piority`,
  `Normal`, and `Low`;
- a route can be generated and its workbook downloaded;
- the app reports no exception in the terminal or browser.

Stop this local check before deploying. Never use the root `app.py` for this
test.

## Deploy

1. Complete the security requirement above.
2. Confirm all intended BlueSG source files, the dedicated entrypoint, and the
   pinned requirements file are committed and pushed to `main`.
3. Sign in to Streamlit Community Cloud and choose **Create app**.
4. Select `DrPinguJr/AMS_Streamlit`.
5. Select branch `main`.
6. Enter `Flexar/BlueSG/streamlit_app.py` as the main file path.
7. Open **Advanced settings** and select Python `3.12`.
8. Paste the three required secrets into the Secrets field.
9. Deploy the app and wait for dependency installation to finish.
10. Open the app, sign in, run one small optimisation, review the map, and
    download the workbook.
11. Restrict access to the intended users before sharing the URL.

## Cloud storage behaviour

Streamlit Community Cloud storage is temporary. A running instance may write
roster changes, route caches, and run summaries, but those files can disappear
after a reboot, redeployment, inactivity shutdown, or replacement of the
instance. More than one session may also share the same running instance.

Therefore:

- treat the repository's safe seed data as the starting state;
- download every workbook that must be kept;
- keep the approved roster in a separate controlled system of record;
- do not depend on Cloud-saved roster edits, caches, or run folders;
- do not use the Cloud filesystem to store personal or confidential records.

Route caches are performance aids and can be rebuilt. A downloaded workbook,
not a file left inside the app, is the durable output.

## Post-deployment checklist

- The URL opens the BlueSG login page, not the full local AMS application.
- An incorrect application password is rejected.
- Both BlueSG pages are visible after login.
- OneMap authentication succeeds without entering a token in the UI.
- Rider priority values remain correct after pasting and editing.
- Optimisation completes without a Python exception.
- Map review and manual reassignment work.
- The final Excel workbook downloads and opens correctly.
- No staff, candidate, rider, credential, cache, or run-output file is publicly
  accessible from GitHub.
- Repository and Streamlit access are limited to approved users.

## Troubleshooting

### The app opens the full AMS system

The wrong entrypoint was selected. Change the main file path to
`Flexar/BlueSG/streamlit_app.py`. Do not use `app.py` or `Home.py`.

### The app says deployment is locked

`APP_PASSWORD` is missing or empty. Add it in Streamlit's Secrets editor, save
the settings, and reboot the app.

### OneMap login or routing fails

Check `ONEMAP_EMAIL` and `ONEMAP_PASSWORD` in Streamlit secrets. Save the
corrected values and reboot. Do not place the credentials in Git or paste a
persistent token into source code.

### A module cannot be imported

Confirm `Flexar/BlueSG/requirements.txt` exists on `main`, contains the four
exact pinned packages above, and the app uses Python 3.12. Reboot after changing
dependencies.

### A file works on Windows but is missing on Cloud

Cloud runs on Linux, where paths and filename casing are exact. Use the main
file path shown above and ensure every imported file is committed with matching
capitalisation. Local Windows launchers and services are intentionally not part
of this deployment.

### Saved roster changes or prior results disappeared

This is expected after a Cloud restart or redeployment. Restore the approved
source roster through the controlled input process and use previously
downloaded workbooks for retained results.

### The app is slow after a restart

The route cache may have been cleared with the temporary filesystem. The first
run can rebuild it; later runs on the same instance should be faster.
