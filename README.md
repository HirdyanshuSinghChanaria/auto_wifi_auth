# Auto WiFi Authentication 📶

A smart, cross-platform background service that automatically logs into Captive Portals (University/Hostel/Hotel WiFi). 

It runs silently in the background, detects when internet access is blocked by a login page, and logs you in automatically using saved credentials.

## 🚀 Features

* **Silent Operation:** Runs in the background (System Tray/Hidden) without annoying popups.
* **Universal Solver:** Automatically analyzes HTML login forms to find Username/Password fields and Hidden Magic Tokens.
* **Fresh Token Logic:** Bypasses "Session Timeouts" by re-fetching fresh login tokens the moment you click connect.
* **Cross-Platform:** Auto-detects OS and uses the correct network tools:
    * **Windows:** Uses `netsh`
    * **macOS:** Uses `networksetup`
* **GUI:** Modern interface (CustomTkinter) that only appears when a *new* unknown network is detected.

## 🛠️ Installation & Setup

### Prerequisites
You need Python installed. Then install the required libraries:

```bash
pip install customtkinter requests beautifulsoup4 pyinstaller
