"""Phase 2 authentication / signed-session tests (no live MySQL required)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-auth-suite")
os.environ["AUTH_REQUIRED"] = "0"

from auth import hash_password  # noqa: E402
from app import app  # noqa: E402


def _active_user(*, user_id: int, store_id: int, username: str, password: str) -> dict:
    return {
        "user_id": user_id,
        "store_id": store_id,
        "username": username,
        "password_hash": hash_password(password),
        "display_name": f"{username} display",
        "is_active": 1,
        "store_name": f"Store {store_id}",
    }


USER_A = _active_user(
    user_id=1,
    store_id=1,
    username="store1_user_a",
    password="demo-store1-pass",
)
USER_B = _active_user(
    user_id=2,
    store_id=2,
    username="store2_user_b",
    password="demo-store2-pass",
)
INACTIVE = {
    **_active_user(
        user_id=3,
        store_id=1,
        username="inactive_user",
        password="unused-pass",
    ),
    "is_active": 0,
}


def _users_by_username() -> dict[str, dict]:
    return {
        USER_A["username"]: USER_A,
        USER_B["username"]: USER_B,
        INACTIVE["username"]: INACTIVE,
    }


def _users_by_id() -> dict[int, dict]:
    return {
        USER_A["user_id"]: USER_A,
        USER_B["user_id"]: USER_B,
        INACTIVE["user_id"]: INACTIVE,
    }


class AuthTests(unittest.TestCase):
    def setUp(self):
        os.environ["AUTH_REQUIRED"] = "0"
        self.client = app.test_client()
        self.username_patch = patch(
            "auth.get_user_by_username",
            side_effect=lambda username: _users_by_username().get((username or "").strip()),
        )
        self.id_patch = patch(
            "auth.get_user_by_id",
            side_effect=lambda user_id: _users_by_id().get(int(user_id)),
        )
        self.username_patch.start()
        self.id_patch.start()

    def tearDown(self):
        self.username_patch.stop()
        self.id_patch.stop()
        os.environ["AUTH_REQUIRED"] = "0"

    def test_valid_login(self):
        response = self.client.post(
            "/auth/login",
            json={"username": "store1_user_a", "password": "demo-store1-pass"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["user"]["user_id"], 1)
        self.assertEqual(payload["user"]["store_id"], 1)
        self.assertEqual(payload["user"]["username"], "store1_user_a")
        self.assertEqual(payload["user"]["store_name"], "Store 1")
        self.assertNotIn("password_hash", payload["user"])
        self.assertNotIn("password", payload["user"])

    def test_invalid_password(self):
        response = self.client.post(
            "/auth/login",
            json={"username": "store1_user_a", "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("Invalid", response.get_json()["error"])

    def test_unknown_user(self):
        response = self.client.post(
            "/auth/login",
            json={"username": "missing_user", "password": "demo-store1-pass"},
        )
        self.assertEqual(response.status_code, 401)

    def test_inactive_user(self):
        response = self.client.post(
            "/auth/login",
            json={"username": "inactive_user", "password": "unused-pass"},
        )
        self.assertEqual(response.status_code, 401)

    def test_auth_me_and_no_password_hash_leakage(self):
        login = self.client.post(
            "/auth/login",
            json={"username": "store1_user_a", "password": "demo-store1-pass"},
        )
        self.assertEqual(login.status_code, 200)

        me = self.client.get("/auth/me")
        self.assertEqual(me.status_code, 200)
        user = me.get_json()["user"]
        self.assertEqual(user["store_id"], 1)
        self.assertEqual(user["username"], "store1_user_a")
        self.assertNotIn("password_hash", user)
        self.assertNotIn("password", user)
        # Entire body must not leak hash material.
        self.assertNotIn("pbkdf2:", me.get_data(as_text=True))
        self.assertNotIn("scrypt:", me.get_data(as_text=True))

    def test_logout_clears_session(self):
        self.client.post(
            "/auth/login",
            json={"username": "store1_user_a", "password": "demo-store1-pass"},
        )
        logout = self.client.post("/auth/logout")
        self.assertEqual(logout.status_code, 200)
        me = self.client.get("/auth/me")
        self.assertEqual(me.status_code, 401)

    def test_two_clients_maintain_independent_sessions(self):
        client_a = app.test_client()
        client_b = app.test_client()

        response_a = client_a.post(
            "/auth/login",
            json={"username": "store1_user_a", "password": "demo-store1-pass"},
        )
        response_b = client_b.post(
            "/auth/login",
            json={"username": "store2_user_b", "password": "demo-store2-pass"},
        )
        self.assertEqual(response_a.status_code, 200)
        self.assertEqual(response_b.status_code, 200)

        me_a = client_a.get("/auth/me").get_json()["user"]
        me_b = client_b.get("/auth/me").get_json()["user"]
        self.assertEqual(me_a["store_id"], 1)
        self.assertEqual(me_a["username"], "store1_user_a")
        self.assertEqual(me_b["store_id"], 2)
        self.assertEqual(me_b["username"], "store2_user_b")

        # Logging out A must not affect B.
        client_a.post("/auth/logout")
        self.assertEqual(client_a.get("/auth/me").status_code, 401)
        still_b = client_b.get("/auth/me")
        self.assertEqual(still_b.status_code, 200)
        self.assertEqual(still_b.get_json()["user"]["store_id"], 2)

    def test_spoofed_store_id_cannot_change_authenticated_store(self):
        response = self.client.post(
            "/auth/login",
            json={
                "username": "store1_user_a",
                "password": "demo-store1-pass",
                "store_id": 999,
                "user_id": 999,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["user"]["store_id"], 1)
        self.assertEqual(response.get_json()["user"]["user_id"], 1)

        me = self.client.get("/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.get_json()["user"]["store_id"], 1)

    @patch("app.chat", return_value={"reply": "ok", "history_text": "ok"})
    def test_chat_remains_accessible_when_auth_required_off(self, mock_chat):
        response = self.client.post(
            "/chat",
            json={"message": "Hello", "history": []},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["reply"], "ok")
        mock_chat.assert_called_once_with("Hello", [], store_id=None)

    @patch("app.get_dashboard_stats", return_value={"total_customers": 5})
    def test_dashboard_remains_accessible_when_auth_required_off(self, mock_stats):
        response = self.client.get("/dashboard/stats")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["total_customers"], 5)
        mock_stats.assert_called_once_with()

    def test_auth_required_flag_blocks_chat_when_enabled(self):
        os.environ["AUTH_REQUIRED"] = "1"
        try:
            response = self.client.post(
                "/chat",
                json={"message": "Hello", "history": []},
            )
            self.assertEqual(response.status_code, 401)
            self.assertIn("Authentication required", response.get_json()["error"])
        finally:
            os.environ["AUTH_REQUIRED"] = "0"


if __name__ == "__main__":
    unittest.main()
