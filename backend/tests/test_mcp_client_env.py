import inspect
import os
import unittest
from unittest.mock import patch

from pawnshop_mcp import client as mcp_client


class McpClientEnvTests(unittest.TestCase):
    def test_server_parameters_forwards_db_credentials_from_parent_env(self):
        parent_env = {
            "PATH": "/usr/bin",
            "HOME": "/home/teller",
            "DB_HOST": "prod-db.example",
            "DB_USER": "teller_user",
            "DB_PASSWORD": "secret-value-not-logged",
            "DB_NAME": "telleriq_db",
            "DB_PORT": "3306",
        }

        with patch.dict(os.environ, parent_env, clear=True):
            params = mcp_client._server_parameters()

        self.assertIsNotNone(params.env)
        self.assertEqual(params.env["DB_HOST"], "prod-db.example")
        self.assertEqual(params.env["DB_USER"], "teller_user")
        self.assertEqual(params.env["DB_PASSWORD"], "secret-value-not-logged")
        self.assertEqual(params.env["DB_NAME"], "telleriq_db")
        self.assertEqual(params.env["DB_PORT"], "3306")

    def test_server_parameters_preserves_ordinary_runtime_variables(self):
        parent_env = {
            "PATH": "/custom/bin:/usr/bin",
            "HOME": "/home/teller",
            "SHELL": "/bin/bash",
            "DB_HOST": "localhost",
            "DB_USER": "root",
            "DB_PASSWORD": "local-secret",
            "DB_NAME": "telleriq_db",
        }

        with patch.dict(os.environ, parent_env, clear=True):
            params = mcp_client._server_parameters()

        self.assertEqual(params.env["PATH"], "/custom/bin:/usr/bin")
        self.assertEqual(params.env["HOME"], "/home/teller")
        self.assertEqual(params.env["SHELL"], "/bin/bash")

    def test_server_parameters_without_optional_db_port_does_not_crash(self):
        parent_env = {
            "PATH": "/usr/bin",
            "HOME": "/home/teller",
            "DB_HOST": "localhost",
            "DB_USER": "root",
            "DB_PASSWORD": "local-secret",
            "DB_NAME": "telleriq_db",
        }

        with patch.dict(os.environ, parent_env, clear=True):
            params = mcp_client._server_parameters()

        self.assertIsNotNone(params.env)
        self.assertEqual(params.env["DB_HOST"], "localhost")
        self.assertNotIn("DB_PORT", params.env)

    def test_no_hardcoded_database_credentials_in_client_source(self):
        source = inspect.getsource(mcp_client)
        for forbidden in (
            "password=",
            "DB_PASSWORD=",
            "prod-db.example",
            "secret-value",
            "your_password",
        ):
            self.assertNotIn(forbidden, source)

        self.assertIn("os.environ.copy()", source)
        self.assertIn("env=", source)


if __name__ == "__main__":
    unittest.main()
