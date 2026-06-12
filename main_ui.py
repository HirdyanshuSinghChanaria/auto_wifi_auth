import customtkinter as ctk
import threading
import time
import sys
from universal_solver import UniversalSolver
from network_manager import NetworkManager
from storage import CredentialStorage

class WifiLoginApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # --- UI Setup ---
        self.title("WiFi Auto-Login")
        self.geometry("400x350")
        self.resizable(False, False)
        
        # Hide window initially (Daemon Mode)
        self.withdraw()
        
        # --- Backend Logic ---
        self.solver = UniversalSolver()
        self.net_man = NetworkManager()
        self.storage = CredentialStorage()
        
        self.current_form = None
        self.is_monitoring = True

        # Fix 9: Track portal IDs where auto-login has been verified to fail,
        # so we don't keep hammering bad credentials in a loop.
        self.failed_portals = set()
        
        # Fix 2: A lock to protect current_form from race conditions
        # between the background thread (writer) and the UI button (reader).
        self._form_lock = threading.Lock()

        # --- UI Components ---
        self.label_status = ctk.CTkLabel(self, text="Login Required", font=("Arial", 20, "bold"))
        self.label_status.pack(pady=20)
        
        self.label_ssid = ctk.CTkLabel(self, text="WiFi: Scanning...", text_color="gray")
        self.label_ssid.pack(pady=(0, 20))
        
        self.entry_user = ctk.CTkEntry(self, placeholder_text="Username/ID", width=250)
        self.entry_user.pack(pady=5)
        
        self.entry_pass = ctk.CTkEntry(self, placeholder_text="Password", show="*", width=250)
        self.entry_pass.pack(pady=5)
        
        self.check_show = ctk.CTkCheckBox(self, text="Show Password", command=self.toggle_pass)
        self.check_show.pack(pady=5)
        
        self.lbl_error = ctk.CTkLabel(self, text="", text_color="orange", font=("Arial", 10))
        self.lbl_error.pack(pady=5)
        
        self.btn_login = ctk.CTkButton(self, text="Connect & Save", command=self.manual_login, width=250, height=40)
        self.btn_login.pack(pady=20)
        
        # Start Background Daemon
        self.monitor_thread = threading.Thread(target=self.background_loop, daemon=True)
        self.monitor_thread.start()
        
        print(">> App started (Hidden). Waiting for network drop...")

    def toggle_pass(self):
        if self.check_show.get() == 1:
            self.entry_pass.configure(show="")
        else:
            self.entry_pass.configure(show="*")

    def show_ui(self, ssid):
        """Surfaces the UI — always called via self.after() for thread safety."""
        self.label_ssid.configure(text=f"WiFi: {ssid}")
        self.lbl_error.configure(text="")
        self.deiconify()
        self.lift()
        self.attributes('-topmost', True)
        self.after_idle(self.attributes, '-topmost', False)

    def verify_internet(self):
        """
        Fix 4: Use NetworkManager.is_connected() which probes Google's
        generate_204 endpoint — clean, purpose-built, and fast.
        """
        return self.net_man.is_connected()

    def background_loop(self):
        """
        The Main Daemon Loop
        """
        while self.is_monitoring:
            time.sleep(5)  # Check every 5 seconds
            
            # 1. Check Internet
            if self.verify_internet():
                # We are online. Go back to sleep.
                continue
            
            print(">> Internet down. Probing...")
            
            # 2. We are offline. Find the Portal.
            portal_response = self.solver.get_portal_page()
            
            if not portal_response:
                # Fluke packet loss or portal unreachable. Retry next loop.
                continue

            # 3. Analyze the Portal
            with self._form_lock:
                self.current_form = self.solver.analyze_page(portal_response)
            
            if not self.current_form:
                print(">> Could not understand login page. Showing UI.")
                # Fix 2: Schedule UI update on main thread
                self.after(0, self.show_ui, "Unknown Network")
                continue

            # 4. Check for Saved Credentials
            ssid = self.net_man.get_ssid() or "Unknown"
            portal_id = self.solver.get_portal_identifier(self.current_form['page_url'])
            
            print(f">> Portal: {ssid} | Host: {portal_id}")

            # Fix 9: Skip auto-login if we already know the saved credentials are bad
            if portal_id in self.failed_portals:
                print(">> Skipping auto-login — previous attempt failed. Showing UI.")
                self.after(0, self.show_ui, ssid)
                while self.state() == "normal":
                    time.sleep(1)
                continue
            
            creds = self.storage.get_credentials(ssid, portal_id)
            
            if creds:
                print(">> Found saved credentials. Attempting Auto-Login...")
                with self._form_lock:
                    form = self.current_form
                self.solver.login(form, creds['user'], creds['password'])
                
                print(">> Verifying connection...")
                time.sleep(3)  # Give firewall time to authorize
                
                if self.verify_internet():
                    print(">> SUCCESS: Internet is ACTUALLY active. Hiding UI.")
                    # Fix 2: Schedule withdraw on main thread
                    self.after(0, self.withdraw)
                else:
                    print(">> FAILURE: Login sent, but still offline.")
                    print(">> Credentials might be wrong. Asking user...")
                    # Fix 9: Mark this portal so we don't auto-retry bad creds
                    self.failed_portals.add(portal_id)
                    # Fix 2: Schedule all UI updates on the main thread
                    def show_failed_ui():
                        self.lbl_error.configure(text="Auto-login failed. Please update password.")
                        self.entry_user.delete(0, 'end')
                        self.entry_user.insert(0, creds['user'])
                        self.show_ui(ssid)
                    self.after(0, show_failed_ui)
                    # Pause loop while user types
                    while self.state() == "normal":
                        time.sleep(1)
            else:
                # No saved creds, show UI
                print(">> No saved credentials. Surfacing UI...")
                self.after(0, self.show_ui, ssid)
                # Pause loop while user types
                while self.state() == "normal":
                    time.sleep(1)

    def manual_login(self):
        with self._form_lock:
            form = self.current_form

        if not form:
            self.lbl_error.configure(text="Error: No login form detected.")
            return

        user = self.entry_user.get()
        password = self.entry_pass.get()
            
        self.lbl_error.configure(text="Connecting...", text_color="blue")
        self.update()
        
        # 1. Send Login Request
        self.solver.login(form, user, password)
        
        # 2. Verify Success
        time.sleep(2)
        if self.verify_internet():
            self.lbl_error.configure(text="Success!", text_color="green")
            self.update()
            
            # 3. Save Credentials ONLY if it actually worked
            ssid = self.net_man.get_ssid() or "Unknown"
            portal_id = self.solver.get_portal_identifier(form['page_url'])
            self.storage.save_credentials(ssid, portal_id, user, password)

            # Fix 9: Clear the failed portals set since user just provided working creds
            self.failed_portals.discard(portal_id)
            
            time.sleep(1)
            # Fix 7: Clear BOTH fields on success for security and clean state
            self.entry_pass.delete(0, 'end')
            self.entry_user.delete(0, 'end')
            self.withdraw()
        else:
            self.lbl_error.configure(text="Login Failed. Check password.", text_color="red")

if __name__ == "__main__":
    app = WifiLoginApp()
    app.mainloop()