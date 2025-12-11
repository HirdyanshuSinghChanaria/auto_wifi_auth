import time
import threading
import customtkinter as ctk
from universal_solver import UniversalSolver
from network_manager import NetworkManager
from storage import StorageManager

class AutoLoginApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # --- UI SETUP ---
        self.title("WiFi Auto-Login")
        self.geometry("420x450") # Made slightly taller
        self.resizable(False, False)
        
        # Title
        self.label = ctk.CTkLabel(self, text="Login Required", font=("Arial", 22, "bold"))
        self.label.pack(pady=(30, 10))
        
        self.sub_label = ctk.CTkLabel(self, text="Detected Captive Portal", font=("Arial", 14), text_color="gray")
        self.sub_label.pack(pady=(0, 20))
        
        # Username
        self.user_entry = ctk.CTkEntry(self, placeholder_text="Username", width=280, height=40)
        self.user_entry.pack(pady=10)
        
        # Password
        self.pass_entry = ctk.CTkEntry(self, placeholder_text="Password", show="*", width=280, height=40)
        self.pass_entry.pack(pady=10)
        
        # Show Password Checkbox
        self.show_pass_var = ctk.BooleanVar(value=False)
        self.show_pass_chk = ctk.CTkCheckBox(
            self, text="Show Password", variable=self.show_pass_var, command=self.toggle_password,
            font=("Arial", 12), width=20, height=20
        )
        self.show_pass_chk.pack(pady=5)
        
        # Status Label
        self.status_label = ctk.CTkLabel(self, text="", text_color="#FF5555", font=("Arial", 12))
        self.status_label.pack(pady=10)
        
        # Connect Button
        self.login_btn = ctk.CTkButton(
            self, text="Connect & Save", command=self.on_submit, width=280, height=50,
            font=("Arial", 15, "bold"), fg_color="#1F6AA5", hover_color="#144870"
        )
        self.login_btn.pack(pady=20)

        # --- LOGIC SETUP ---
        self.solver = UniversalSolver()
        self.net = NetworkManager()
        self.store = StorageManager()
        
        self.current_ssid = None
        
        # Start Hidden
        print(">> App started (Hidden). Waiting for network drop...")
        self.withdraw()
        self.after(1000, self.check_network_loop)

    def toggle_password(self):
        """Toggles the password masking"""
        if self.show_pass_var.get():
            self.pass_entry.configure(show="")
        else:
            self.pass_entry.configure(show="*")

    def check_network_loop(self):
        """Main Loop running on Main Thread"""
        checker_thread = threading.Thread(target=self.background_logic)
        checker_thread.daemon = True
        checker_thread.start()

    def background_logic(self):
        try:
            # 1. Check Internet
            if self.net.is_connected():
                # print(f">> [{time.ctime()}] Online. Sleeping...") 
                self.after(10000, self.check_network_loop)
                return

            # 2. Offline -> Probe
            print(">> Internet down. Probing...")
            portal_page = self.solver.get_portal_page()
            
            if not portal_page:
                print(">> No portal found. Retrying...")
                self.after(5000, self.check_network_loop)
                return

            # 3. Portal Found
            self.current_ssid = self.net.get_ssid() or "Unknown Network"
            portal_id = self.solver.get_portal_identifier(portal_page.url)
            
            print(f">> Portal: {self.current_ssid} | Host: {portal_id}")

            # 4. Check Saved Creds
            creds = self.store.get_credentials(self.current_ssid)
            if not creds:
                creds = self.store.find_by_portal_id(portal_id)

            if creds:
                print(">> Auto-Login with saved creds...")
                # We fetch a FRESH page here to ensure the token isn't stale
                fresh_page = self.solver.get_portal_page() 
                if fresh_page:
                    form_info = self.solver.analyze_page(fresh_page)
                    if self.solver.login(form_info, creds['username'], creds['password']):
                        print(">> Auto-Login Success!")
                    else:
                        print(">> Auto-Login Failed (Bad Creds?)")
                
                self.after(5000, self.check_network_loop)
            else:
                # 5. Unknown -> Show UI
                print(">> Surfacing UI for user input...")
                self.show_login_ui()

        except Exception as e:
            print(f"Error in background: {e}")
            self.after(10000, self.check_network_loop)

    def show_login_ui(self):
        """Update UI and Show Window"""
        self.sub_label.configure(text=f"WiFi: {self.current_ssid}")
        
        # Clear fields
        self.user_entry.delete(0, 'end')
        self.pass_entry.delete(0, 'end')
        self.status_label.configure(text="")
        
        # Pop up
        self.deiconify()
        self.lift()
        self.attributes('-topmost', True)
        self.attributes('-topmost', False)

    def on_submit(self):
        """User Clicked Connect"""
        u = self.user_entry.get()
        p = self.pass_entry.get()
        
        if not u or not p:
            self.status_label.configure(text="Please enter username and password")
            return
        
        self.status_label.configure(text="Getting fresh token...", text_color="orange")
        self.update()
        
        # CRITICAL FIX: Fetch a FRESH token right now!
        # Do not use the old cached page from 1 minute ago.
        try:
            fresh_page = self.solver.get_portal_page()
            if not fresh_page:
                self.status_label.configure(text="Error: Could not reach login page.")
                return

            self.status_label.configure(text="Logging in...")
            self.update()

            form_info = self.solver.analyze_page(fresh_page)
            if not form_info:
                self.status_label.configure(text="Error: Login form not found.")
                return

            # Perform Login
            result = self.solver.login(form_info, u, p)
            
            if result and result.status_code == 200:
                # Double check internet
                time.sleep(1)
                if self.net.is_connected():
                    self.status_label.configure(text="Success! Connected.", text_color="green")
                    self.update()
                    
                    # Save Credentials ONLY on success
                    self.store.save_credentials(
                        self.current_ssid, u, p, 
                        self.solver.get_portal_identifier(fresh_page.url)
                    )
                    
                    time.sleep(1.5)
                    self.withdraw() # Hide window
                    self.check_network_loop() # Resume monitoring
                else:
                    self.status_label.configure(text="Login sent, but no Internet.\nWrong Password?", text_color="red")
            else:
                self.status_label.configure(text=f"Login Rejected (Server {result.status_code})", text_color="red")

        except Exception as e:
            self.status_label.configure(text=f"Error: {str(e)}", text_color="red")
            print(e)

if __name__ == "__main__":
    app = AutoLoginApp()
    app.mainloop()