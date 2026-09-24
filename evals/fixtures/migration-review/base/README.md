# Events service

Production runs PostgreSQL 16 (`config/database.yml`). Every API request
appends to the `events` table, which holds ~200M rows and takes ~2k inserts/s
at peak; deploys are rolling, with migrations run by the first new instance
while the old release keeps serving traffic.
