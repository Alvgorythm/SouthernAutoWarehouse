# PullList

Every night, GitHub runs this app. It checks eBay sell-through for each part on the junkyard's new vehicles and publishes a pull list you can open on your phone.

## Files
- `pulllist.py`: the app
- `template.html`: the pull list page design
- `config.json`: parts to check, default threshold, sandbox or production
- `vehicles.csv`: today's vehicles (the yard scraper will fill this in automatically)
- `.github/workflows/nightly.yml`: the nightly schedule
- `docs/index.html`: the published pull list (rebuilt every run)
- `logs/api_log.txt`: every eBay API call from the last run (created on first run)

## Setup
1. Create a new repo on GitHub and upload these files, keeping the folders.
2. Settings > Secrets and variables > Actions > New repository secret:
   - `EBAY_CLIENT_ID` = your Sandbox App ID
   - `EBAY_CLIENT_SECRET` = your Sandbox Cert ID
3. Settings > Pages > Source: "Deploy from a branch", Branch: `main`, Folder: `/docs`. Save.
4. Actions tab > Nightly pull list > Run workflow.
5. Your list is at `https://YOURUSERNAME.github.io/REPONAME/`

## Changing things
- Parts to check: edit the `parts` list in `config.json`
- Default threshold: `threshold` in `config.json` (the slider on the page overrides it)
- Run time: the `cron` line in the workflow file (UTC)
- After eBay approval: set `environment` to `production` and swap in your Production keys
