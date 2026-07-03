import logging
import threading
import time

import customtkinter as ctk

from app_logging import setup_logging
from network_manager import NetworkManager
from storage import CredentialStorage
from universal_solver import UniversalSolver

log = logging.getLogger(__name__)

CHECK_INTERVAL = 5      # seconds between connectivity checks
UI_POLL_INTERVAL = 10   # while the window is open, how often to re-check internet
UI_SNOOZE_SECONDS = 60  # after the user dismisses the window, don't re-open it for this long


class WifiLoginApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # --- UI Setup ---
        self.title("WiFi Auto-Login")
        self.geometry("400x400")
        self.resizable(False, False)

        # Hide window initially (Daemon Mode)
        self.withdraw()

        # Closing the window must hide it, not kill the daemon.
        self.protocol("WM_DELETE_WINDOW", self.hide_ui)

        # --- Backend Logic ---
        self.solver = UniversalSolver()
        self.net_man = NetworkManager()
        self.storage = CredentialStorage()

        self.current_form = None
        self.is_monitoring = True
        self.portal_fail_count = 0

        # Portal IDs where auto-login has been verified to fail, so we don't
        # keep hammering bad credentials in a loop.
        self.failed_portals = set()

        # Protects current_form between the daemon thread and UI callbacks.
        self._form_lock = threading.Lock()

        # Set (always on the main thread) when the window is hidden again.
        # The daemon thread waits on this instead of polling Tk state, which
        # is neither thread-safe nor race-free.
        self._ui_closed = threading.Event()
        self._ui_closed.set()

        # If the user dismisses the window while still offline, don't shove
        # it back in their face on the next 5-second cycle.
        self._ui_snooze_until = 0.0

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
        self.btn_login.pack(pady=(15, 8))

        self.btn_quit = ctk.CTkButton(
            self, text="Quit App", command=self.quit_app,
            width=100, height=24, fg_color="transparent",
            border_width=1, text_color="gray"
        )
        self.btn_quit.pack(pady=(0, 12))

        # Start Background Daemon
        self.monitor_thread = threading.Thread(target=self.background_loop, daemon=True)
        self.monitor_thread.start()

        log.info("App started (hidden). Waiting for network drop...")

    def toggle_pass(self):
        if self.check_show.get() == 1:
            self.entry_pass.configure(show="")
        else:
            self.entry_pass.configure(show="*")

    # ------------------------------------------------------------------
    # Main-thread UI helpers (always invoked via self.after from workers)
    # ------------------------------------------------------------------

    def show_ui(self, ssid, error=None, error_color="orange", prefill_user=None):
        """Surfaces the window. Must run on the main thread."""
        self.label_ssid.configure(text=f"WiFi: {ssid}")
        self.lbl_error.configure(text=error or "", text_color=error_color)
        if prefill_user is not None:
            self.entry_user.delete(0, 'end')
            self.entry_user.insert(0, prefill_user)
        self.deiconify()
        self.lift()
        self.attributes('-topmost', True)
        self.after_idle(self.attributes, '-topmost', False)

    def hide_ui(self):
        """Hides the window and lets the daemon thread resume."""
        self.withdraw()
        self._ui_closed.set()

    def quit_app(self):
        log.info("Quit requested. Shutting down.")
        self.is_monitoring = False
        self._ui_closed.set()  # release the daemon thread if it is waiting
        self.destroy()

    # ------------------------------------------------------------------
    # Daemon thread
    # ------------------------------------------------------------------

    def verify_internet(self):
        return self.net_man.is_connected()

    def background_loop(self):
        """The Main Daemon Loop."""
        while self.is_monitoring:
            time.sleep(CHECK_INTERVAL)
            if not self.is_monitoring:
                break
            try:
                self._monitor_once()
            except Exception:
                # The daemon must survive anything (Tk teardown mid-call,
                # network weirdness, parser surprises). Log and keep going.
                log.exception("Unexpected error in daemon loop")

    def _monitor_once(self):
        # 1. Check Internet
        if self.verify_internet():
            self.portal_fail_count = 0
            return

        log.info("Internet down. Probing...")

        # 2. We are offline. Find the Portal.
        portal_response = self.solver.get_portal_page()

        if not portal_response:
            # Fluke packet loss or portal unreachable. Retry next loop.
            self.portal_fail_count += 1
            log.info("No portal found. (Attempt %d/3)", self.portal_fail_count)
            if self.portal_fail_count >= 3:
                self.portal_fail_count = 0
                log.info("Repeatedly failed to find portal. Surfacing UI.")
                ssid = self.net_man.get_ssid() or "Unknown"
                self._surface_ui_and_wait(
                    ssid, error="No internet & no login portal found.", error_color="red"
                )
            return

        # 3. Analyze the Portal
        self.portal_fail_count = 0
        form = self.solver.analyze_page(portal_response)
        with self._form_lock:
            self.current_form = form

        ssid = self.net_man.get_ssid() or "Unknown"

        if not form:
            log.warning("Could not understand login page. Showing UI.")
            self._surface_ui_and_wait(
                ssid, error="Couldn't auto-detect the login form. Try a browser.",
                error_color="red"
            )
            return

        # 4. Check for Saved Credentials
        portal_id = self.solver.get_portal_identifier(form['page_url'])
        log.info("Portal: %s | Host: %s", ssid, portal_id)

        # Skip auto-login if we already know the saved credentials are bad
        if portal_id in self.failed_portals:
            log.info("Skipping auto-login — previous attempt failed. Showing UI.")
            self._surface_ui_and_wait(ssid)
            return

        creds = self.storage.get_credentials(ssid, portal_id)

        if not creds:
            log.info("No saved credentials. Surfacing UI...")
            self._surface_ui_and_wait(ssid)
            return

        log.info("Found saved credentials. Attempting auto-login...")
        self.solver.login(form, creds['user'], creds['password'])

        log.info("Verifying connection...")
        time.sleep(3)  # Give the firewall time to authorize

        if self.verify_internet():
            log.info("SUCCESS: Internet is active. Hiding UI.")
            self.after(0, self.hide_ui)
        else:
            log.warning("Login sent, but still offline. Credentials might be wrong. Asking user.")
            # Mark this portal so we don't auto-retry bad creds
            self.failed_portals.add(portal_id)
            self._surface_ui_and_wait(
                ssid, error="Auto-login failed. Please update password.",
                prefill_user=creds['user']
            )

    def _surface_ui_and_wait(self, ssid, error=None, error_color="orange", prefill_user=None):
        """
        Shows the window from the daemon thread, then blocks until the user
        dismisses it — or the internet comes back (e.g. they logged in
        through a browser), in which case the window is hidden automatically.
        """
        if time.monotonic() < self._ui_snooze_until:
            return

        self._ui_closed.clear()
        self.after(0, self.show_ui, ssid, error, error_color, prefill_user)

        while not self._ui_closed.wait(timeout=UI_POLL_INTERVAL):
            if not self.is_monitoring:
                return
            if self.verify_internet():
                log.info("Internet restored while window was open. Hiding UI.")
                self.after(0, self.hide_ui)

        # Dismissed but still offline: the user chose not to log in right
        # now, so snooze re-surfacing instead of re-opening every 5 seconds.
        if self.is_monitoring and not self.verify_internet():
            self._ui_snooze_until = time.monotonic() + UI_SNOOZE_SECONDS

    # ------------------------------------------------------------------
    # Manual login (button) — network work runs off the main thread
    # ------------------------------------------------------------------

    def manual_login(self):
        with self._form_lock:
            form = self.current_form

        if not form:
            self.lbl_error.configure(text="Error: No login form detected.", text_color="red")
            return

        user = self.entry_user.get()
        password = self.entry_pass.get()

        self.btn_login.configure(state="disabled")
        self.lbl_error.configure(text="Connecting...", text_color="gray")

        threading.Thread(
            target=self._manual_login_worker,
            args=(form, user, password),
            daemon=True,
        ).start()

    def _manual_login_worker(self, form, user, password):
        try:
            # 1. Send Login Request (login() re-fetches fresh tokens first)
            self.solver.login(form, user, password)

            # 2. Verify Success
            time.sleep(2)
            success = self.verify_internet()

            if success:
                # 3. Save Credentials ONLY if it actually worked
                ssid = self.net_man.get_ssid() or "Unknown"
                portal_id = self.solver.get_portal_identifier(form.get('page_url', ''))
                self.storage.save_credentials(ssid, portal_id, user, password)
                # User just provided working creds — portal is no longer "failed"
                self.failed_portals.discard(portal_id)

            self.after(0, self._on_manual_login_done, success)
        except Exception:
            log.exception("Manual login failed unexpectedly")
            try:
                self.after(0, self._on_manual_login_done, False)
            except Exception:
                pass  # window already destroyed

    def _on_manual_login_done(self, success):
        self.btn_login.configure(state="normal")
        if success:
            self.lbl_error.configure(text="Success!", text_color="green")
            # Clear BOTH fields on success for security and clean state
            self.entry_pass.delete(0, 'end')
            self.entry_user.delete(0, 'end')
            self.after(800, self.hide_ui)
        else:
            self.lbl_error.configure(text="Login Failed. Check password.", text_color="red")


if __name__ == "__main__":
    setup_logging()
    app = WifiLoginApp()
    app.mainloop()
