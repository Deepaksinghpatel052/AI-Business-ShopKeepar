#!/bin/sh
set -e

# Safety net: if DATABASE_URL points at a sqlite file whose parent directory
# doesn't exist yet (e.g. a fresh checkout, or a volume mount that wasn't
# pre-created), create it now instead of failing with an opaque
# "unable to open database file" error from alembic/sqlite3.
python3 -c "
import os, re, pathlib
url = os.environ.get('DATABASE_URL', 'sqlite:///./bizinsight.db')
m = re.match(r'^sqlite:///(.*)$', url)
if m:
    path = m.group(1)
    if not path.startswith('/'):
        path = os.path.join(os.getcwd(), path)
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
"

echo "[entrypoint] Running database migrations..."
alembic upgrade head

echo "[entrypoint] Starting app..."
exec "$@"
