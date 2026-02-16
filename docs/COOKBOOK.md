Calendar Lab – Operational Cookbook

This document describes how to operate, maintain, and recover the Calendar Lab system.
All procedures listed here are known to work and were tested during development.

––––––––––––––––––––
	1.	Accessing the server
––––––––––––––––––––

Connect to the Ubuntu VM using SSH with your normal user (rasjrbr).
All Docker operations are executed from this user’s home directory unless stated otherwise.

––––––––––––––––––––
2. Project location
––––––––––––––––––––

The Calendar Lab project lives in the following directory:

/home/rasjrbr/calendar-lab

This directory contains:
	•	docker-compose / compose.yaml
	•	worker source code
	•	configuration files
	•	documentation

Always operate Docker from this directory to avoid running the wrong stack.

––––––––––––––––––––
3. Starting the full stack
––––––––––––––––––––

Starting the stack brings up:
	•	PostgreSQL (calendar_postgres)
	•	Worker (calendar_worker)
	•	NGINX (calendar_nginx)

Once started:
	•	The worker will begin ingesting the source ICS on its interval
	•	PostgreSQL will store parsed events
	•	NGINX will expose the final ICS files

––––––––––––––––––––
4. Stopping the stack
––––––––––––––––––––

Stopping the stack shuts down all containers cleanly but preserves:
	•	Database data (Postgres volume)
	•	Generated ICS files (calendar_output volume)

This is safe and does not delete user data.

––––––––––––––––––––
5. Restarting services
––––––––––––––––––––

Restarting only the worker is useful when:
	•	You changed parsing logic
	•	You wiped user data and want a clean re-ingest
	•	The worker crashed or stalled

Restarting the entire stack is rarely required unless:
	•	Volumes were changed
	•	Docker networking was modified

––––––––––––––––––––
6. Rebuilding after code changes
––––––––––––––––––––

When Python code inside the worker changes:
	•	The worker image must be rebuilt
	•	Containers must be restarted

If behavior looks unchanged after a rebuild, it is likely Docker cache.
In that case, rebuild without cache.

––––––––––––––––––––
7. Logs and troubleshooting
––––––––––––––––––––

Worker logs are the primary debugging source.
They show:
	•	Ingestion count
	•	Deduplication behavior
	•	Timezone conversion
	•	ICS generation

Postgres logs are only needed if:
	•	Connections fail
	•	Schema changes cause errors

NGINX logs are rarely needed unless:
	•	ICS is not accessible via browser
	•	Port mapping fails

––––––––––––––––––––
8. Verifying the output calendar
––––––––––––––––––––

The generated ICS files are written to a shared volume mounted at:

/var/www/calendars

Each user has one file:
	•	roque.ics
	•	future users will follow the same pattern

You can verify output by:
	•	Checking the file timestamp
	•	Opening it in a browser
	•	Subscribing via webcal or https

––––––––––––––––––––
9. Wiping poisoned data (safe reset)
––––––––––––––––––––

If parsing logic was wrong (timezone, titles, duplication), user data may be poisoned.

Safe reset procedure:
	•	Delete the user’s rows from the raw_events table
	•	Do NOT delete volumes
	•	Do NOT delete containers

On the next worker cycle, the calendar will be fully re-ingested and rebuilt.

––––––––––––––––––––
10. Database sanity checks
––––––––––––––––––––

You can query the database to confirm:
	•	Number of events ingested
	•	Whether duplicates are being prevented
	•	Whether wipes were successful

Database checks are read-only unless explicitly deleting user data.

––––––––––––––––––––
11. Portainer (Docker UI)
––––––––––––––––––––

Portainer is installed and accessible via port 9000.

Use Portainer for:
	•	Visual container health
	•	Quick restarts
	•	Volume inspection

Do NOT:
	•	Edit containers manually
	•	Change environment variables in Portainer
	•	Use it for development logic

Portainer is operational visibility only.

––––––––––––––––––––
12. Known limitations
––––––––––––––––––––
	•	iFlightNeo source calendar is destructive and unstable
	•	Floating time events must always be assumed local
	•	Past data beyond ~2 months is intentionally ignored
	•	Output calendars are disposable and regenerated at will

––––––––––––––––––––
13. Golden rules
––––––––––––––––––––
	•	Never trust the source calendar
	•	Database is the source of truth
	•	Always rebuild after logic changes
	•	Always validate timezone first
	•	Regulation logic always uses local BRT internally