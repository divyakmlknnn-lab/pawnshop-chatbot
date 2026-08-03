import logging
import os
import sys

from dotenv import load_dotenv
from flask import Flask, g, jsonify, request
from flask_cors import CORS

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from auth import (
    authenticate_username_password,
    auth_gate_response,
    clear_session,
    configure_session,
    load_request_identity,
)
from database import get_dashboard_stats, verify_schema
from llm_chat import chat
from tenant_sql import parse_trusted_store_id, tenancy_enforcement_enabled

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
configure_session(app)
CORS(app)


@app.before_request
def _load_auth_identity():
    # Populate trusted identity when a signed session exists.
    # Does not block requests unless AUTH_REQUIRED is enabled.
    load_request_identity()
    blocked = auth_gate_response(request.path)
    if blocked is not None:
        return blocked


@app.after_request
def set_utf8_charset(response):
    content_type = response.content_type or ""
    if content_type.startswith("application/json") and "charset=" not in content_type:
        response.headers["Content-Type"] = "application/json; charset=utf-8"
    return response


@app.route("/")
def home():
    return jsonify({"status": "TellerIQ LLM backend is running."})


@app.route("/health")
def health():
    try:
        verify_schema()
        return jsonify({"status": "ok", "database": "telleriq_db schema valid"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 503


@app.route("/auth/login", methods=["POST"])
def auth_login():
    body = request.get_json(silent=True) or {}
    username = body.get("username")
    password = body.get("password")
    # Intentionally ignore any client-supplied store_id / user_id.
    profile = authenticate_username_password(username, password)
    if profile is None:
        return jsonify({"error": "Invalid username or password."}), 401
    return jsonify({"user": profile})


@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    clear_session()
    return jsonify({"ok": True})


@app.route("/auth/me", methods=["GET"])
def auth_me():
    profile = load_request_identity()
    if profile is None:
        return jsonify({"error": "Not authenticated."}), 401
    return jsonify({"user": profile})


@app.route("/dashboard/stats", methods=["GET"])
def dashboard_stats_endpoint():
    try:
        # Never trust client-supplied store identity (query/body/headers).
        if tenancy_enforcement_enabled():
            trusted_store_id = parse_trusted_store_id(getattr(g, "store_id", None))
            if trusted_store_id is None:
                return jsonify({"error": "Authentication required."}), 401
            return jsonify(get_dashboard_stats(store_id=trusted_store_id))
        # TENANCY_ENFORCEMENT=0: preserve historical global dashboard behavior.
        return jsonify(get_dashboard_stats())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/chat", methods=["POST"])
def chat_endpoint():
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    history = body.get("history") or []

    if not message:
        return jsonify({"error": "message is required"}), 400

    try:
        # Trusted store identity from authenticated session / g only.
        # Never accept store_id from request JSON (Gemini must never control it).
        body.pop("store_id", None)
        trusted_store_id = getattr(g, "store_id", None)
        result = chat(message, history, store_id=trusted_store_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def run_startup_checks():
    db_name = os.environ.get("DB_NAME", "telleriq_db")
    if db_name != "telleriq_db":
        print(
            f"WARNING: DB_NAME is '{db_name}'. Expected 'telleriq_db'.",
            file=sys.stderr,
        )
    if not os.environ.get("GEMINI_API_KEY"):
        print(
            "WARNING: GEMINI_API_KEY is not set. Operational queries still work; "
            "general chat fallback will fail until a key is configured.",
            file=sys.stderr,
        )
    if not (os.environ.get("SECRET_KEY") or "").strip():
        print(
            "WARNING: SECRET_KEY is not set. Using local development session "
            "fallback. Set SECRET_KEY before shared or deployed use.",
            file=sys.stderr,
        )
    verify_schema()
    print("Schema check passed for telleriq_db.")


if __name__ == "__main__":
    try:
        run_startup_checks()
    except Exception as e:
        print(f"STARTUP ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    app.run(debug=True, port=5000)
