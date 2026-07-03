import json
import logging
import os
import platform
import sys

log = logging.getLogger(__name__)

# Sentinel SSIDs used when detection fails. Credentials must never be matched
# by these — two different networks can both look "Unknown".
UNKNOWN_SSIDS = {None, "", "Unknown", "Unknown Network"}


def get_data_dir():
    """
    Returns a persistent directory for storing app data.
    This survives PyInstaller temp extraction and app restarts.

    macOS:   ~/Library/Application Support/WifiAutoLogin/
    Windows: %APPDATA%/WifiAutoLogin/
    Linux:   ~/.config/WifiAutoLogin/
    """
    system = platform.system()

    if system == "Darwin":  # macOS
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    elif system == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:  # Linux
        base = os.environ.get("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config"))

    data_dir = os.path.join(base, "WifiAutoLogin")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


# Persistent path that works both in development AND in a PyInstaller .app bundle
DB_FILE = os.path.join(get_data_dir(), "wifi_map.json")

# Service name used as the namespace in OS Keychain
KEYRING_SERVICE = "WifiAutoLogin"


def _get_keyring():
    """
    Tries to import keyring. Returns the module if available, None otherwise.
    This lets the app still work (with plaintext fallback) if keyring isn't installed.
    """
    try:
        import keyring
        return keyring
    except ImportError:
        return None


class CredentialStorage:
    def __init__(self, filename=DB_FILE):
        self.filename = filename
        self.keyring = _get_keyring()
        self.ensure_file_exists()
        self._migrate_old_data()
        self._migrate_plaintext_to_keyring()

        if self.keyring:
            log.info("Using OS Keychain for passwords")
        else:
            log.warning("'keyring' not installed. Passwords stored in plaintext. Run: pip install keyring")
        log.info("Metadata database: %s", self.filename)

    def _migrate_old_data(self):
        """
        One-time migration: if an old wifi_map.json exists next to the script
        (from before the persistent storage fix), merge it into the new location
        and rename the old file to .bak so it doesn't re-import every launch.
        """
        if getattr(sys, 'frozen', False):
            old_dir = os.path.dirname(sys.executable)
        else:
            old_dir = os.path.dirname(os.path.abspath(__file__))

        old_file = os.path.join(old_dir, "wifi_map.json")

        if not os.path.exists(old_file) or os.path.abspath(old_file) == os.path.abspath(self.filename):
            return

        try:
            with open(old_file, 'r') as f:
                old_data = json.load(f)

            if not old_data:
                return

            new_data = self._read_data()
            merged = {**old_data, **new_data}

            with open(self.filename, 'w') as f:
                json.dump(merged, f, indent=4)

            backup = old_file + ".bak"
            os.rename(old_file, backup)
            log.info("Migrated %d entries from old database. Backup: %s", len(old_data), backup)
        except Exception as e:
            log.warning("Migration skipped (error: %s)", e)

    def _migrate_plaintext_to_keyring(self):
        """
        One-time migration: moves any plaintext passwords from wifi_map.json
        into the OS Keychain, then removes them from the JSON file.
        """
        if not self.keyring:
            return

        data = self._read_data()
        migrated = 0

        for key, info in data.items():
            if 'password' in info:
                try:
                    self.keyring.set_password(KEYRING_SERVICE, key, info['password'])
                    del info['password']
                    migrated += 1
                except Exception as e:
                    log.warning("Keyring migration failed for %s: %s", key, e)

        if migrated > 0:
            with open(self.filename, 'w') as f:
                json.dump(data, f, indent=4)
            log.info("Moved %d password(s) from plaintext to OS Keychain.", migrated)

    def ensure_file_exists(self):
        """Creates the JSON database if it doesn't exist."""
        if not os.path.exists(self.filename):
            try:
                with open(self.filename, 'w') as f:
                    json.dump({}, f)
            except Exception as e:
                log.error("Error creating DB: %s", e)

    def _read_data(self):
        """Helper to read the JSON file safely."""
        try:
            with open(self.filename, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def save_credentials(self, ssid, portal_id, username, password):
        """
        Saves credentials.
        - SSID + username go to wifi_map.json (non-sensitive metadata)
        - Password goes to OS Keychain (encrypted by the OS)
        - Falls back to plaintext JSON if keyring is not available
        """
        data = self._read_data()

        key = portal_id if portal_id else ssid

        data[key] = {
            "ssid": ssid,
            "user": username,
        }

        # Store password in OS Keychain if available
        if self.keyring:
            try:
                self.keyring.set_password(KEYRING_SERVICE, key, password)
            except Exception as e:
                log.warning("Keychain save failed, falling back to plaintext: %s", e)
                data[key]["password"] = password
        else:
            # Fallback: store in JSON (plaintext)
            data[key]["password"] = password

        try:
            with open(self.filename, 'w') as f:
                json.dump(data, f, indent=4)
            log.info("Credentials saved for %s (Key: %s)", ssid, key)
        except Exception as e:
            log.error("Error saving credentials: %s", e)

    def get_credentials(self, ssid, portal_id):
        """
        Retrieves credentials.
        Priority 1: Match by Portal IP (Strongest match)
        Priority 2: Match by SSID (Fallback)

        Password is fetched from OS Keychain first, then falls back to JSON.
        """
        data = self._read_data()
        entry = None
        entry_key = None

        # 1. Try Strict Match (Portal IP/Domain)
        if portal_id and portal_id in data:
            entry = data[portal_id]
            entry_key = portal_id

        # 2. Try SSID Match (Fallback) — but never for unknown/sentinel SSIDs.
        # Two unrelated networks can both be "Unknown", and matching on that
        # would send saved credentials to the wrong portal.
        if not entry and ssid not in UNKNOWN_SSIDS:
            for key, info in data.items():
                if info.get('ssid') == ssid:
                    entry = info
                    entry_key = key
                    break

        if not entry:
            return None

        # Fetch password: Keychain first, then JSON fallback
        password = None
        if self.keyring and entry_key:
            try:
                password = self.keyring.get_password(KEYRING_SERVICE, entry_key)
            except Exception as e:
                log.warning("Keychain read failed: %s", e)

        if not password:
            password = entry.get('password')

        if not password:
            return None

        return {
            "ssid": entry.get("ssid"),
            "user": entry.get("user"),
            "password": password,
        }