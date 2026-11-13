"""TaskFlow API - a small REST API for a to-do list, backed by PostgreSQL.

Every setting comes from environment variables, so the same container image
runs unchanged on your laptop, in Docker Compose and in Kubernetes.
"""
import logging
import os
import socket
import time
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, jsonify, request

# ---------------------------------------------------------------------------
# Configuration (12-factor style: read everything from the environment)
# ---------------------------------------------------------------------------
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "5432")),
    "dbname": os.environ.get("DB_NAME", "taskflow"),
    "user": os.environ.get("DB_USER", "taskflow"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "connect_timeout": 3,
}
APP_VERSION = os.environ.get("APP_VERSION", "dev")
HOSTNAME = socket.gethostname()  # in Kubernetes this is the Pod name

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("taskflow")

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
@contextmanager
def db_cursor():
    """Open a connection, hand back a cursor, commit on success, always close."""
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn:  # commits if the block succeeds, rolls back on an exception
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                yield cur
    finally:
        conn.close()


def init_db(retries=10, delay=3):
    """Create the tasks table, retrying while the database is still starting."""
    for attempt in range(1, retries + 1):
        try:
            with db_cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tasks (
                        id         SERIAL PRIMARY KEY,
                        title      VARCHAR(200) NOT NULL,
                        done       BOOLEAN      NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
                    )
                    """
                )
            log.info("Database ready (attempt %d)", attempt)
            return
        except psycopg2.OperationalError as exc:
            log.warning("Database not ready (attempt %d/%d): %s", attempt, retries, exc)
            time.sleep(delay)
    raise RuntimeError("Could not connect to the database")


# ---------------------------------------------------------------------------
# Health endpoints - used by Docker HEALTHCHECK and Kubernetes probes
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    """Liveness: is the process alive? Never touches the database."""
    return jsonify(status="ok"), 200


@app.get("/api/ready")
def ready():
    """Readiness: can this instance serve real traffic (is the DB reachable)?"""
    try:
        with db_cursor() as cur:
            cur.execute("SELECT 1")
        return jsonify(status="ready"), 200
    except psycopg2.Error as exc:
        log.error("Readiness check failed: %s", exc)
        return jsonify(status="not ready"), 503


@app.get("/api/info")
def info():
    """Shows which container/Pod answered - handy for seeing load balancing."""
    return jsonify(version=APP_VERSION, hostname=HOSTNAME)


# ---------------------------------------------------------------------------
# Task endpoints (CRUD)
# ---------------------------------------------------------------------------
@app.get("/api/tasks")
def list_tasks():
    with db_cursor() as cur:
        cur.execute("SELECT id, title, done, created_at FROM tasks ORDER BY id")
        return jsonify(cur.fetchall())


@app.post("/api/tasks")
def create_task():
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    if not title or len(title) > 200:
        return jsonify(error="title is required (1-200 characters)"), 400
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO tasks (title) VALUES (%s) RETURNING id, title, done, created_at",
            (title,),
        )
        return jsonify(cur.fetchone()), 201


@app.patch("/api/tasks/<int:task_id>")
def toggle_task(task_id):
    with db_cursor() as cur:
        cur.execute(
            "UPDATE tasks SET done = NOT done WHERE id = %s "
            "RETURNING id, title, done, created_at",
            (task_id,),
        )
        row = cur.fetchone()
    if row is None:
        return jsonify(error="task not found"), 404
    return jsonify(row)


@app.delete("/api/tasks/<int:task_id>")
def delete_task(task_id):
    with db_cursor() as cur:
        cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
        deleted = cur.rowcount
    if deleted == 0:
        return jsonify(error="task not found"), 404
    return "", 204


# Create the table when the app starts (tests set SKIP_DB_INIT=1 to skip this).
if os.environ.get("SKIP_DB_INIT") != "1":
    init_db()
