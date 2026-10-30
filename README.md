# Job Application Dashboard

A live view of the job-application pipeline: total and daily submissions,
today's applications with email-confirmation status, and every parked
application that is waiting on a human step — ordered deadline-first.

- **Live page:** https://varun050201.github.io/job-application-dashboard/
- **Data:** `data.json`, regenerated daily from the pipeline ledger and park
  registry. The page itself is static and reads `data.json`.
- **Privacy:** the published page contains no email addresses, phone numbers,
  street addresses, or local file paths — only company names, roles, req IDs,
  statuses, and public apply links.
- **Daily refresh:** a scheduled job regenerates `data.json` every evening
  and pushes it here; GitHub Actions republishes the page on every push.
