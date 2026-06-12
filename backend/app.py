import logging
import os
import sys

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from database import verify_schema
from llm_chat import chat

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
CORS(app)


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


@app.route("/chat", methods=["POST"])
def chat_endpoint():
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    history = body.get("history") or []

    if not message:
        return jsonify({"error": "message is required"}), 400

    try:
        result = chat(message, history)
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
    verify_schema()
    print("Schema check passed for telleriq_db.")


if __name__ == "__main__":
    try:
        run_startup_checks()
    except Exception as e:
        print(f"STARTUP ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    app.run(debug=True, port=5000)
