
## SIH Demo Database Reset

The release includes `reset_wattwise_database.bat`. Run `start_wattwise.bat` once so the virtual environment exists, stop the app, then run the reset utility. It clears all WattWise application tables in the configured `DATABASE_URL` and creates a fresh `Demo MSME` company with a new one-time API key. Type `RESET` when prompted.

The reset is intentionally explicit and is never performed automatically on startup.
