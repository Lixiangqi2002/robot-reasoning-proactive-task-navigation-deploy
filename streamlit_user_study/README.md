# Robot Reasoning of Proactive Task and Navigation Decision

This is a Streamlit questionnaire draft for reviewing short simulated robot
scenes. The participant-facing page uses plain English and includes an
information sheet / consent step before any scene questions are shown.

For deployment, the app reads static trial assets from:

`streamlit_user_study/assets/`

If that directory is absent, it falls back to the local external data root:

`/media/selina-xiangqi/New Volume/dsg_dataset/user_study_data/`

The app renders the current study order:

1. Q1 / Study 2A: person-object pair rating
2. Q2 / Study 1: robot scene understanding
3. Q3 / Study 2B: robot plan and reasoning
4. Q4 / Study 3B: updated goal-route task support

## Run

```bash
cd "/home/selina-xiangqi/Documents/ChatGPT/icra 2027"
python3 -m pip install -r streamlit_user_study/requirements.txt
streamlit run streamlit_user_study/app.py
```

## Deploy on Streamlit Community Cloud

Push this folder to a GitHub repository, then create a Streamlit Community Cloud
app with:

```text
Main file path: streamlit_user_study/app.py
```

The deployed URL will look like:

```text
https://your-app-name.streamlit.app/
```

The app currently includes the first 4 review scenes in
`streamlit_user_study/assets/`.

Optional query parameters:

```text
?participant_id=participant_001&bundle_id=B001
?trial_ids=trial_dir_name_1,trial_dir_name_2
```

Responses are saved to Supabase when Streamlit secrets contain a `[supabase]`
section. If Supabase is not configured, the app falls back to Google Sheets when
`[responses]` is configured. If neither cloud backend is configured, responses
fall back to a local CSV:

`streamlit_user_study/responses/user_study_responses.csv`

### Supabase response storage

Recommended setup for Streamlit Community Cloud:

1. In Supabase, open the SQL Editor and run
   `streamlit_user_study/supabase_schema.sql`.
2. In Supabase, open `Project Settings -> API`.
3. Copy the project URL and a key. For this server-side Streamlit app, the
   `service_role` key is simplest; an `anon` key also works if the table has a
   Row Level Security insert policy.
4. In Streamlit Cloud, open the app settings, go to `Secrets`, and paste a
   `[supabase]` block using `streamlit_user_study/secrets.example.toml` as the
   template.

Do not commit real Supabase keys to GitHub.

### Google Sheets response storage

Recommended setup for Streamlit Community Cloud:

1. Create a Google Sheet with a tab named `responses`.
2. Create a Google Cloud service account and download its JSON key.
3. Share the Google Sheet with the service account email as an Editor.
4. In Streamlit Cloud, open the app settings, go to `Secrets`, and paste the
   values using `streamlit_user_study/secrets.example.toml` as the template.

Do not commit the real service account key to GitHub.

## Static assets

Only the files used by the form are copied into `assets/`. To refresh the static
asset bundle from the local dataset:

```bash
python3 streamlit_user_study/scripts/prepare_static_assets.py
```

Current pilot bundle size is about 24 MB for 4 trials. The largest file is about
1.1 MB, so the static assets are Git-friendly for the current pilot. For the full
65-trial study, expect the folder to be larger; use a private repository and
consider Git LFS only if individual files become large.

## Option order

Q3 and Q4 randomize the display order of options by default. The order is
stable for the same participant, bundle, trial, and question section, so a page
refresh will not reshuffle the form. The CSV records the shown order in the
`display_order` column.

To disable this for debugging:

```bash
DSG_RANDOMIZE_OPTION_ORDER=0 streamlit run streamlit_user_study/app.py
```
