#!/usr/bin/env bash
# regenerates db/schema.sql from the stand's database after `dbmate up`
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec -T postgres pg_dump -U postgres --schema-only --no-owner --no-privileges postgres > db/schema.sql
