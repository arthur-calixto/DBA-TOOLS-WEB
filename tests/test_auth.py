import time
import unittest
from starlette.requests import Request
from unittest.mock import patch

from cryptography.fernet import Fernet
from starlette.responses import Response
from app.config import settings


class AuthTests(unittest.TestCase):
    def test_csrf_accepts_same_origin_from_request_host_when_base_url_unset(self):
        from app.auth import _csrf_value, validate_csrf
        token = "session-token"
        headers = [(b"cookie", f"dba_tools_session={token}".encode()),
                   (b"x-csrf-token", _csrf_value(token).encode()),
                   (b"origin", b"http://10.40.0.17:8591"),
                   (b"host", b"10.40.0.17:8591")]
        scope = {"type": "http", "method": "POST", "scheme": "http", "path": "/monitor/analisar",
                 "headers": headers, "query_string": b"", "server": ("10.40.0.17", 8591)}
        with patch.object(settings, "auth_enabled", True), patch.object(settings, "public_base_url", ""):
            validate_csrf(Request(scope))
    def setUp(self):
        from app.config import settings

        self.key = Fernet.generate_key().decode()
        self.settings_patch = patch.multiple(
            settings,
            auth_session_key=self.key,
            auth_cookie_max_age_seconds=30 * 24 * 3600,
            auth_cookie_renew_threshold_seconds=7 * 24 * 3600,
            auth_cookie_secure=True,
        )
        self.settings_patch.start()

    def tearDown(self):
        self.settings_patch.stop()

    def test_argon2id_hash_and_password_policy(self):
        from app.auth import hash_password, verify_password

        hashed = hash_password("senha extremamente segura")
        self.assertTrue(hashed.startswith("$argon2id$"))
        self.assertTrue(verify_password("senha extremamente segura", hashed))
        self.assertFalse(verify_password("senha errada", hashed))
        with self.assertRaises(ValueError):
            hash_password("curta")

    def test_encrypted_session_has_expiration_and_tamper_protection(self):
        from app.auth import _decode_session, issue_session

        user = type("User", (), {"id": 4, "auth_version": 3})()
        token = issue_session(user)
        payload = _decode_session(token)
        self.assertEqual(payload["uid"], 4)
        self.assertEqual(payload["ver"], 3)
        with self.assertRaises(Exception):
            _decode_session(token[:-2] + "xx")

    def test_expired_session_is_rejected(self):
        from app.auth import _issue_session, _decode_session

        with patch("app.auth.time.time", return_value=1000):
            token = _issue_session(4, 1)
        with patch("app.auth.time.time", return_value=1000 + 30 * 24 * 3600 + 1):
            with self.assertRaises(Exception):
                _decode_session(token)

    def test_cookie_is_persistent_http_only_and_secure(self):
        from app.auth import set_session_cookie

        response = Response()
        set_session_cookie(response, "encrypted-token")
        cookies = "\n".join(value.decode() for key, value in response.raw_headers if key == b"set-cookie")
        self.assertIn("Max-Age=2592000", cookies)
        self.assertIn("HttpOnly", cookies)
        self.assertIn("Secure", cookies)
        self.assertIn("SameSite=lax", cookies)

    def test_csrf_value_is_bound_to_session_cookie(self):
        from app.auth import _csrf_value

        self.assertNotEqual(_csrf_value("token-a"), _csrf_value("token-b"))

    def test_permissions_are_denied_by_default(self):
        from app.auth import AuthenticatedUser, has_permission

        user = AuthenticatedUser(1, "user", False, {})
        self.assertFalse(has_permission(user, "diagnostics.execute"))
        self.assertFalse(has_permission(AuthenticatedUser(1, "user", False, {"diagnostics.execute": "yes"}), "diagnostics.execute"))
        self.assertTrue(has_permission(AuthenticatedUser(1, "admin", True, {}), "anything"))

    def test_auth_enabled_requires_database_and_valid_key(self):
        from app.config import Settings

        with self.assertRaises(ValueError):
            Settings(auth_enabled=True, database_url=None, auth_session_key=None)


if __name__ == "__main__":
    unittest.main()
