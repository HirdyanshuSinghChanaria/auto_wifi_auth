import logging
import platform
import re
import subprocess

import requests

log = logging.getLogger(__name__)

# Single source of truth for connectivity checks. The solver probes the same
# URL, so "offline" and "portal found" can never disagree about what online means.
# The Microsoft probe returns a fixed plaintext body, which captive portals
# replace or redirect — that difference is how we detect them.
PROBE_URL = "http://www.msftconnecttest.com/connecttest.txt"
PROBE_EXPECTED_TEXT = "Microsoft Connect Test"

# How long to wait for a CLI utility before giving up (seconds)
SUBPROCESS_TIMEOUT = 5


class NetworkManager:
    def __init__(self):
        self.os_type = platform.system()

    def get_ssid(self):
        """
        Cross-platform method to get the current connected WiFi SSID.
        Returns: String (SSID name) or None.
        """
        try:
            if self.os_type == "Windows":
                return self._get_ssid_windows()
            elif self.os_type == "Darwin":  # macOS
                return self._get_ssid_macos()
            elif self.os_type == "Linux":
                return self._get_ssid_linux()
            else:
                return None
        except Exception as e:
            log.warning("Error getting SSID: %s", e)
            return None

    def _get_ssid_windows(self):
        # Uses 'netsh' to find the connected interface
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        process = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT,
            startupinfo=startupinfo
        )
        match = re.search(r'^\s*SSID\s*:\s*(.*)$', process.stdout, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return None

    def _get_ssid_macos(self):
        # Method 1: 'networksetup' — works on most macOS versions
        for iface in ("en0", "en1"):
            try:
                process = subprocess.run(
                    ["networksetup", "-getairportnetwork", iface],
                    capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT
                )
                # Output format: "Current Wi-Fi Network: SSID_NAME"
                # maxsplit=1 so SSIDs that themselves contain ": " survive intact
                if "Current Wi-Fi Network" in process.stdout:
                    return process.stdout.split(": ", 1)[1].strip()
            except (subprocess.SubprocessError, OSError, IndexError):
                continue

        # Method 2: 'ipconfig getsummary' — networksetup can report
        # "not associated" on macOS 14+ (Sonoma) even when connected
        for iface in ("en0", "en1"):
            try:
                process = subprocess.run(
                    ["ipconfig", "getsummary", iface],
                    capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT
                )
                match = re.search(r'^\s*SSID\s*:\s*(.+)$', process.stdout, re.MULTILINE)
                if match:
                    return match.group(1).strip()
            except (subprocess.SubprocessError, OSError):
                continue

        return None

    def _get_ssid_linux(self):
        try:
            process = subprocess.run(
                ["iwgetid", "-r"],
                capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT
            )
            return process.stdout.strip() or None
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            try:
                process = subprocess.run(
                    ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
                    capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT
                )
                match = re.search(r'^yes:(.*)$', process.stdout, re.MULTILINE)
                if match:
                    return match.group(1).strip()
            except (FileNotFoundError, subprocess.SubprocessError, OSError):
                pass
            return None

    def is_connected(self):
        """
        Checks for REAL internet access.
        Returns True only if the probe body comes back unmodified — a captive
        portal serving its login page (or redirecting) fails the text check.
        """
        try:
            # Short timeout to keep the daemon loop responsive
            response = requests.get(PROBE_URL, timeout=3)
            return PROBE_EXPECTED_TEXT in response.text
        except requests.RequestException:
            return False


# --- TEST BLOCK ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    nm = NetworkManager()
    print(f"OS: {nm.os_type}")
    print(f"SSID: {nm.get_ssid()}")
    print(f"Online: {nm.is_connected()}")
