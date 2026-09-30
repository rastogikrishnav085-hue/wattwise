# Putting WattWise online (free): Supabase + Render + Streamlit Cloud

You will end up with a public dashboard link you can send to anyone. Nothing
here costs money and none of it needs a credit card.

**How the pieces fit**

```
  Streamlit Community Cloud          Render (free)
  the dashboard (app.py)             the API (api.py)
            \                         /
             \                       /
              Supabase (free Postgres)
              one shared database
```

The dashboard and the API are two separate front doors to the same
database. Neither needs to talk to the other.

Do the parts in order. Each step is small.

---

## Part 1 — Test it, then put the project on GitHub

**Always do this before pushing** — it catches errors before they go online.

1. Unzip `wattwise_v2.zip`.
2. Run `start_wattwise.bat` (or `./start_wattwise.sh`) once. This sets up
   everything and runs the automated test suite. Watch for
   `XXX passed` near the end — if you see `FAILED` instead, stop and fix
   that first (or send me what it says).
3. With the dashboard open in your browser, click through it by hand:
   sign up a company, log in, click **Run forecast**, check all 6 tabs
   load, try both download buttons. Close it with CTRL+C when done.

### Push to GitHub (automated)

1. Make a free account at https://github.com if you don't have one.
2. Click **New repository**. Name it `wattwise`. Leave everything else as
   it is (do **not** tick "Add a README"). Click **Create repository**,
   then copy the URL it shows you.
3. In a terminal inside the unzipped folder, run:

   - **Windows:** double-click `push_to_github.bat`
   - **Mac/Linux:** `./push_to_github.sh`

4. The first time, it will ask for that GitHub URL — paste it. It also
   asks for your name/email once per machine if git has never been used
   there before (any email works, it doesn't need to be verified).
5. It re-runs the full test suite first. **If anything fails, it stops
   and does not push** — fix the error, run it again.
6. On every later change, just run the same script again (optionally
   `push_to_github.bat "what you changed"` for a custom commit message).
   It only pushes if the tests still pass.

## Part 2 — Supabase (the database)

1. Go to https://supabase.com and sign up (GitHub login is easiest).
2. Click **New project**. Pick any name, choose the region closest to you,
   and set a **database password**. Write it down now, you cannot read it
   again later. Prefer letters and numbers only. Special characters like
   `@` or `#` break the connection string unless you encode them.
3. Wait about two minutes for the project to finish setting up.
4. Click the **Connect** button at the top of the project page.
5. Choose **Session pooler**. This matters. Do **not** use "Direct
   connection": it is IPv6-only, and Render's free tier cannot reach it.
   The Session pooler works over IPv4 and is free.
6. Copy the connection string. It looks like this:

```
postgresql://postgres.abcdefghijklmnop:[YOUR-PASSWORD]@aws-0-eu-west-1.pooler.supabase.com:5432/postgres
```

7. Replace `[YOUR-PASSWORD]` (including the square brackets) with your real
   password. Keep this finished string somewhere private. It is your
   `DATABASE_URL`.

### Test it from your own computer before deploying

You do not need to create any tables. WattWise creates them itself on first
connection.

1. Run `start_wattwise.bat` once so the `.venv` folder exists, then close it
   with CTRL+C once the dashboard opens.
2. In a terminal inside the project folder, run these one at a time:

```
.venv\Scripts\activate
set DATABASE_URL=postgresql://postgres.abcdefghijklmnop:YOUR_REAL_PASSWORD@aws-0-eu-west-1.pooler.supabase.com:5432/postgres
python scripts\check_database.py
python scripts\bootstrap.py
```

(In PowerShell, use `$env:DATABASE_URL="..."` instead of `set`.)

3. You should see `Backend : PostgreSQL (Supabase): ...` and `[OK] Connected` and a
   **demo API key**. Save it.
4. In Supabase, open **Table Editor**. You should now see tables named
   `companies`, `forecast_runs` and so on. That confirms it works.

If it fails, see Troubleshooting at the bottom.

---

## Part 3 — Render (the API)

1. Go to https://render.com and sign up with GitHub.
2. Click **New +** then **Blueprint**. Connect your `wattwise` repository.
   Render reads the `render.yaml` file in the project and fills in the
   settings for you.
3. When it asks for `DATABASE_URL`, paste your full Supabase string from
   Part 2.
4. Click **Apply** and wait for the build (a few minutes).
5. When it says **Live**, open your URL (it looks like
   `https://wattwise-api.onrender.com`) and add `/health` to the end. You
   should see `{"status":"ok"}`.
6. Add `/docs` instead to see the interactive API page. Each endpoint
   there has an `x-api-key` box: paste the key you saved to try the
   protected ones (`/forecast`, `/history`, and so on).

---

## Part 4 — Streamlit Community Cloud (the dashboard)

1. Go to https://share.streamlit.io and sign in with GitHub.
2. Click **Create app**, then choose your `wattwise` repository.
3. Set **Branch** to `main` and **Main file path** to `app.py`.
4. Click **Advanced settings**.
   - Set **Python version** to 3.12.
   - In the **Secrets** box, paste exactly this, with your real string:

```
DATABASE_URL = "postgresql://postgres.abcdefghijklmnop:YOUR_REAL_PASSWORD@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
```

5. Click **Deploy**. The first build takes a few minutes.
6. Open your new `https://something.streamlit.app` link.

---

## Part 5 — Use it

1. On the dashboard, use the **New company — sign up** tab. Fill in the
   company details and click **Create company**.
2. Copy the API key it shows. It is displayed **once**.
3. Switch to the **Log in** tab, paste the key, and log in.
4. Click **Run forecast** in the sidebar.

Companies created on the dashboard also work on the API, and the other way
round, because they share one database.

---

## Things to know about free tiers

- **Render sleeps** after about 15 minutes with no traffic. The first
  request afterwards can take 30 to 60 seconds. Open the `/health` link a
  minute before you demo it.
- **Streamlit apps sleep** after a period of no visitors. Click the wake-up
  button when you open it. Open it a few minutes before presenting.
- **Supabase free projects pause** if unused for a while. If the app
  suddenly cannot connect, open the Supabase dashboard and click
  **Restore project**.
- **Trained models are not kept between restarts.** Free hosts wipe their
  disk. This does not break anything: every forecast retrains in a few
  seconds. All your data (companies, runs, recommendations, consultant
  notes) lives in Supabase and is kept.
- **Never commit your `DATABASE_URL`** or paste it into a public place. If
  it leaks, reset the database password in Supabase (Project Settings,
  Database) and update Render and Streamlit.

---

## Troubleshooting

| What you see | What it means | Fix |
|---|---|---|
| `could not translate host name` or `Network is unreachable` | You used the Direct connection string | Use the **Session pooler** string (Part 2, step 5) |
| `password authentication failed` | Wrong password, or wrong username | The username must be `postgres.` followed by your project ref, exactly as Supabase shows it. Re-check the password |
| `FATAL: Tenant or user not found` | Username is plain `postgres` | Use the full `postgres.<project-ref>` username from the Session pooler string |
| Password has `@`, `#` or `/` and it fails | Special characters break a URL | Reset the password to letters and numbers only |
| Render build fails on the Python version | The pinned version is not offered | In Render, open Environment and delete the `PYTHON_VERSION` line, or set it to another 3.12.x |
| Streamlit says `ModuleNotFoundError` | A dependency did not install | Check the logs (bottom-right, **Manage app**); confirm `requirements.txt` is in the repo root |
| Everything works but old data is missing | You are connected to a different database | Compare the `DATABASE_URL` in Render, Streamlit and your local terminal |

## Optional Part 4B — Vercel for the FastAPI API

Vercel supports FastAPI as a Python Function. WattWise includes `api/index.py`
plus `vercel.json` as an optional Vercel adapter. The Streamlit dashboard should
remain on Streamlit Community Cloud; Vercel is for the API layer.

1. Push the repository to GitHub first.
2. In Vercel, import the GitHub repository.
3. Keep the project root at the repository root.
4. Add these environment variables in Vercel:
   - `DATABASE_URL` — your Supabase Session-pooler connection string.
   - `GEMINI_API_KEY` — your Gemini key, if using Gemini on the API.
   - `WATTWISE_USE_GEMINI=true`
   - `GEMINI_MODEL=gemini-3.8-flash`
   - `WATTWISE_ENV=production`
5. Deploy. Vercel detects the FastAPI application through `api/index.py`.
6. Test the deployment at the Vercel URL and its `/health` and `/docs` routes.

For the simplest SIH deployment, Render remains the recommended API path in this
project because the existing `render.yaml` is already configured. Vercel is an
optional alternative for the API, not a replacement for the Streamlit dashboard.
