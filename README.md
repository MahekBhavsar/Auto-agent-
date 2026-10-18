# Daily status automation (Google Chat)

1. In your Google Chat space: **Apps & integrations -> Webhooks** -> create one, copy the URL.
2. `cp .env.example .env` and paste the URL into `GOOGLE_CHAT_WEBHOOK`.
3. Every morning run `python daily_status.py` (add it to Task Scheduler / cron / startup).

Flow: paste Start Report -> posted + tasks become a checklist -> every 2h a popup
(New / In Progress / Done per task, add new tasks) posts the `Update:` message -> at
`END_TIME` the Daily End Report popup is posted. Use `--start`, `--update`, `--end`
to run a single step. Python 3 standard library only (tkinter for popups).
