"""Tests unitaires pour app/auth.py."""
from __future__ import annotations

import time
import unittest

from app.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing(unittest.TestCase):
    def test_hash_is_not_plaintext(self) -> None:
        h = hash_password("secret123")
        self.assertNotIn("secret123", h)

    def test_verify_correct_password(self) -> None:
        h = hash_password("correct_password")
        self.assertTrue(verify_password("correct_password", h))

    def test_reject_wrong_password(self) -> None:
        h = hash_password("correct_password")
        self.assertFalse(verify_password("wrong_password", h))

    def test_different_hashes_same_password(self) -> None:
        """Deux hashes du même mot de passe doivent être différents (salt aléatoire)."""
        h1 = hash_password("password")
        h2 = hash_password("password")
        self.assertNotEqual(h1, h2)
        self.assertTrue(verify_password("password", h1))
        self.assertTrue(verify_password("password", h2))

    def test_verify_corrupted_hash_returns_false(self) -> None:
        self.assertFalse(verify_password("any", "not_valid_base64!!!"))

    def test_verify_empty_hash_returns_false(self) -> None:
        self.assertFalse(verify_password("any", ""))


class TestJWT(unittest.TestCase):
    def test_create_and_decode_token(self) -> None:
        token = create_access_token("alice")
        self.assertEqual(decode_access_token(token), "alice")

    def test_invalid_token_returns_none(self) -> None:
        self.assertIsNone(decode_access_token("not.a.valid.token"))

    def test_tampered_token_returns_none(self) -> None:
        token = create_access_token("alice")
        tampered = token[:-5] + "XXXXX"
        self.assertIsNone(decode_access_token(tampered))

    def test_empty_token_returns_none(self) -> None:
        self.assertIsNone(decode_access_token(""))

    def test_token_contains_username(self) -> None:
        for username in ["alice", "bob123", "user_with_underscores"]:
            with self.subTest(username=username):
                token = create_access_token(username)
                self.assertEqual(decode_access_token(token), username)


if __name__ == "__main__":
    unittest.main()
