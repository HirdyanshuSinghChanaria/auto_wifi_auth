import json
import os

# CONSTANTS
DB_FILE = "wifi_map.json"

class StorageManager:
    def __init__(self):
        self.db = self._load_db()

    def _load_db(self):
        """Loads the JSON database."""
        if not os.path.exists(DB_FILE):
            return {}
        try:
            with open(DB_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading DB: {e}")
            return {}

    def _save_db(self):
        """Saves the JSON database to disk."""
        try:
            with open(DB_FILE, 'w') as f:
                json.dump(self.db, f, indent=4)
        except Exception as e:
            print(f"Error saving DB: {e}")

    def save_credentials(self, ssid, username, password, portal_id=None):
        """
        Saves credentials to a simple JSON file.
        WARNING: Passwords are visible if you open the file.
        """
        self.db[ssid] = {
            "username": username,
            "password": password,  # Stored as plain text
            "portal_id": portal_id
        }
        self._save_db()
        print(f"[{ssid}] Credentials saved to {DB_FILE}.")

    def get_credentials(self, ssid):
        """
        Retrieves credentials for a specific SSID.
        """
        if ssid in self.db:
            return self.db[ssid]
        return None

    def find_by_portal_id(self, portal_id):
        """
        Finds credentials if the SSID changed but the Portal Host is the same.
        """
        if not portal_id:
            return None

        for saved_ssid, data in self.db.items():
            if data.get("portal_id") == portal_id:
                print(f"Match found via Portal ID! (Original SSID: {saved_ssid})")
                return data # Returns the dict containing username/password
        return None

# --- TEST BLOCK ---
if __name__ == "__main__":
    store = StorageManager()
    
    # Test Saving
    store.save_credentials("TEST_WIFI", "my_user", "my_secret_pass", "http://1.1.1.1")
    
    # Test Retrieving
    creds = store.get_credentials("TEST_WIFI")
    if creds:
        print(f"Retrieved: {creds['username']} / {creds['password']}")
    
    # Check the file
    print(f"\nCheck the '{DB_FILE}' file in this folder. You will see the password there.")