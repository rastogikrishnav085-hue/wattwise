# WattWise + Supabase

Supabase is used here as the shared PostgreSQL database for company accounts, API-key hashes, forecast runs, recommendations, consultant notes and audit logs. The application schema is created automatically by SQLAlchemy on startup.

## 1. Create the project
1. Create a Supabase project.
2. Open **Connect**.
3. For Render/IPv4 environments, use the **Shared pooler — Session mode** connection string.
4. Replace `[YOUR-PASSWORD]` with the database password. If the password contains reserved URL characters, percent-encode them.

## 2. Put the connection string in the deployment service
Do not put it in GitHub. Set `DATABASE_URL` as a secret environment variable in Render and Streamlit Cloud.

Example shape:

`postgresql://postgres.PROJECT_REF:PASSWORD@POOLER_HOST:5432/postgres`

## 3. Do NOT upload the raw CSV into Supabase for this version
The current WattWise pipeline reads CSV/TXT through the dashboard or from the local `data/` folder. Supabase stores application/forecast metadata, not the raw meter file. This avoids unnecessarily storing potentially sensitive electricity data in the application database.

If you later want persistent raw-file storage, add a Supabase Storage bucket or a dedicated readings table as a separate feature.

## 4. Initialize/test
Local CMD:

`copy .env.example .env`

Then fill `DATABASE_URL` and run:

`call .venv\Scripts\activate.bat`
`python scripts\check_database.py`

`bootstrap.py`/the application will create the required tables automatically.
