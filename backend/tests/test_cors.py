"""Credentialed CORS allowlist tests (local frontend POC)."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-cors-suite")
os.environ.setdefault(
    "CORS_ORIGINS",
    "http://127.0.0.1:8000,http://localhost:8000",
)
os.environ["AUTH_REQUIRED"] = "0"

from app import app  # noqa: E402


class CredentialedCorsTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_allowed_origin_127_is_reflected_not_star(self):
        response = self.client.get(
            "/health",
            headers={"Origin": "http://127.0.0.1:8000"},
        )
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "http://127.0.0.1:8000",
        )
        self.assertNotEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "*",
        )
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Credentials"),
            "true",
        )

    def test_allowed_origin_localhost_is_reflected(self):
        response = self.client.get(
            "/auth/me",
            headers={"Origin": "http://localhost:8000"},
        )
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "http://localhost:8000",
        )
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Credentials"),
            "true",
        )

    def test_unapproved_origin_not_granted_credentialed_access(self):
        response = self.client.get(
            "/health",
            headers={"Origin": "http://evil.example.com"},
        )
        allow_origin = response.headers.get("Access-Control-Allow-Origin")
        self.assertNotEqual(allow_origin, "*")
        self.assertNotEqual(allow_origin, "http://evil.example.com")

    def test_preflight_from_local_frontend_allows_credentials(self):
        response = self.client.options(
            "/auth/login",
            headers={
                "Origin": "http://127.0.0.1:8000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertIn(response.status_code, {200, 204})
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "http://127.0.0.1:8000",
        )
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Credentials"),
            "true",
        )

    def test_protected_path_preflight_succeeds_with_auth_required(self):
        os.environ["AUTH_REQUIRED"] = "1"
        try:
            for path, method in (("/chat", "POST"), ("/dashboard/stats", "GET")):
                response = self.client.options(
                    path,
                    headers={
                        "Origin": "http://127.0.0.1:8000",
                        "Access-Control-Request-Method": method,
                        "Access-Control-Request-Headers": "content-type",
                    },
                )
                self.assertIn(response.status_code, {200, 204}, path)
                self.assertEqual(
                    response.headers.get("Access-Control-Allow-Origin"),
                    "http://127.0.0.1:8000",
                )
                self.assertEqual(
                    response.headers.get("Access-Control-Allow-Credentials"),
                    "true",
                )
                self.assertNotEqual(
                    response.headers.get("Access-Control-Allow-Origin"),
                    "*",
                )
        finally:
            os.environ["AUTH_REQUIRED"] = "0"


if __name__ == "__main__":
    unittest.main()
