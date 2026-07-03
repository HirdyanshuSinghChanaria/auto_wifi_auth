"""Unit tests for credential lookup rules (keyring disabled, temp files only)."""
import os
import tempfile
import unittest

from storage import CredentialStorage


def make_storage(filename):
    """Builds a CredentialStorage without running __init__, so tests never
    touch the real database, keychain, or migration paths."""
    storage = CredentialStorage.__new__(CredentialStorage)
    storage.filename = filename
    storage.keyring = None
    return storage


class TestGetCredentials(unittest.TestCase):
    def setUp(self):
        fd, self.dbfile = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        self.storage = make_storage(self.dbfile)
        self.storage.ensure_file_exists()

    def tearDown(self):
        os.unlink(self.dbfile)

    def test_portal_id_match(self):
        self.storage.save_credentials("CampusNet", "10.0.0.1:8090", "alice", "pw1")
        creds = self.storage.get_credentials("CampusNet", "10.0.0.1:8090")
        self.assertEqual(creds['user'], 'alice')
        self.assertEqual(creds['password'], 'pw1')

    def test_ssid_fallback_for_known_ssid(self):
        self.storage.save_credentials("CampusNet", "10.0.0.1:8090", "alice", "pw1")
        # Different portal id, same SSID -> fallback should find it
        creds = self.storage.get_credentials("CampusNet", "10.9.9.9:8090")
        self.assertIsNotNone(creds)
        self.assertEqual(creds['user'], 'alice')

    def test_unknown_ssid_never_matches_by_ssid(self):
        # An entry saved when SSID detection failed
        self.storage.save_credentials("Unknown", "10.0.0.1:8090", "alice", "pw1")
        # A different, unrecognized portal whose SSID also failed detection
        # must NOT receive alice's credentials.
        creds = self.storage.get_credentials("Unknown", "172.16.0.1:1000")
        self.assertIsNone(creds)

    def test_no_match_returns_none(self):
        self.assertIsNone(self.storage.get_credentials("Nowhere", "1.2.3.4"))


if __name__ == "__main__":
    unittest.main()
