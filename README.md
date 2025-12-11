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

---

## 👨‍💻 For Developers: Running from Source

If you have Python installed and want to run the raw script to test changes:

1.  **Install Requirements:**
    ```bash
    pip install customtkinter requests beautifulsoup4 pyinstaller
    ```

2.  **Run the App:**
    ```bash
    # Windows
    python main_ui.py
    
    # macOS
    python3 main_ui.py
    ```

**Tip for Windows Developers:** To run it invisibly without the black command window, rename the file to `main_ui.pyw` and double-click it.

---

## 📦 For Users: Building the Executable

To create a standalone file (`.exe` for Windows or `.app` for Mac) that runs without Python, follow these steps on the specific OS.

### 🪟 Building on Windows
*Note: You must build the Windows .exe on a Windows computer.*

1.  Open PowerShell in the project folder.
2.  Run this build command:
    ```powershell
    python -m PyInstaller --noconsole --onefile --name "WifiLogin" --collect-all customtkinter main_ui.py
    ```
3.  **Output:** Go to the `dist/` folder. You will find **`WifiLogin.exe`**.
4.  **To Use:** Send this `.exe` file to your friends. They just double-click it to run.

### 🍎 Building on macOS
*Note: You must build the Mac .app on a Mac.*

1.  Open Terminal in the project folder.
2.  Run this build command:
    ```bash
    pyinstaller --noconsole --name "WifiAutoLogin" --collect-all customtkinter main_ui.py
    ```
3.  **Output:** Go to the `dist/` folder. You will find **`WifiAutoLogin.app`**.
4.  **To Use:** * Right-click the `.app` -> "Compress" to zip it.
    * Send the `.zip` to friends.
    * They must drag it to their **Applications** folder and double-click.

---

## 📂 Project Structure

* `main_ui.py`: The Main Application (GUI + Background Loop).
* `universal_solver.py`: The Logic Engine (Scrapes HTML, handles Tokens/Cookies).
* `network_manager.py`: The Hardware Layer (Talks to Windows/Mac OS network adapters).
* `storage.py`: Handles saving and retrieving credentials (JSON).

## 📝 License
Free to use for educational purposes.
