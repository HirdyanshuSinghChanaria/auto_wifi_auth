import subprocess
import platform
import re
import requests
import time

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
            print(f"Error getting SSID: {e}")
            return None

    def _get_ssid_windows(self):
        # Uses 'netsh' to find the connected interface
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        process = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, startupinfo=startupinfo
        )
        match = re.search(r'^\s*SSID\s*:\s*(.*)$', process.stdout, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return None

    def _get_ssid_macos(self):
        # Method 1: Modern 'networksetup' command (Works on all modern macOS)
        # This is much more reliable than the private 'airport' framework path
        try:
            process = subprocess.run(
                ["networksetup", "-getairportnetwork", "en0"],
                capture_output=True, text=True
            )
            # Output format: "Current Wi-Fi Network: SSID_NAME"
            if "Current Wi-Fi Network" in process.stdout:
                ssid = process.stdout.split(": ")[1].strip()
                return ssid
        except Exception:
            pass

        # Method 2: Fallback to System Profiler (Slower but accurate)
        try:
            process = subprocess.run(
                ["/usr/sbin/networksetup", "-getairportnetwork", "en1"], # Try en1 just in case
                capture_output=True, text=True
            )
            if "Current Wi-Fi Network" in process.stdout:
                return process.stdout.split(": ")[1].strip()
        except:
            pass
            
        return None

    def _get_ssid_linux(self):
        try:
            process = subprocess.run(["iwgetid", "-r"], capture_output=True, text=True)
            return process.stdout.strip()
        except FileNotFoundError:
            try:
                process = subprocess.run(
                    ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
                    capture_output=True, text=True
                )
                match = re.search(r'^yes:(.*)$', process.stdout, re.MULTILINE)
                if match:
                    return match.group(1).strip()
            except:
                pass
            return None

    def is_connected(self):
        """
        Checks for REAL internet access.
        Returns True if we get a 204 (No Content) from Google.
        Returns False if we get a 200 (Login Page) or error.
        """
        try:
            # Short timeout to keep the UI responsive
            response = requests.get("http://clients3.google.com/generate_204", timeout=3)
            if response.status_code == 204:
                return True
            return False
        except requests.RequestException:
            return False

# --- TEST BLOCK ---
if __name__ == "__main__":
    nm = NetworkManager()
    print(f"OS: {nm.os_type}")
    print(f"SSID: {nm.get_ssid()}")
    print(f"Online: {nm.is_connected()}")