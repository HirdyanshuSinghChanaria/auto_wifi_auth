import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re

class UniversalSolver:
    def __init__(self):
        # Create a session to store cookies (essential for session-based firewalls)
        self.session = requests.Session()
        
        # Mimic a modern Laptop (Windows 10 Chrome) to avoid being blocked
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })

    def get_portal_identifier(self, full_url):
        """
        Extracts the unique 'Host' from the URL.
        Use this to identify the portal even if the SSID changes.
        """
        parsed = urlparse(full_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def get_portal_page(self):
        """
        Probes the network.
        Returns: 
        - response object (if trapped in portal)
        - "ONLINE" string (if internet is working)
        - None (if network is down/unreachable)
        """
        print(">> Probing network...")
        try:
            # Probe 1: NeverSSL (HTTP)
            response = self.session.get("http://neverssl.com", timeout=10, allow_redirects=True)
            
            # If we see "NeverSSL" text, we are actually ONLINE.
            if "NeverSSL" in response.text:
                return "ONLINE"
            
            # Otherwise, we are at a login page
            return response

        except requests.exceptions.RequestException:
            # Probe 2: Fallback to Cloudflare IP (Bypass DNS errors)
            try:
                response = self.session.get("http://1.1.1.1", timeout=5, allow_redirects=True)
                if "Cloudflare" in response.text:
                    return "ONLINE"
                return response
            except:
                return None

    def analyze_page(self, response):
        """
        Scrapes HTML to find the login form structure.
        Handles standard HTML Forms AND JavaScript Redirects.
        """
        soup = BeautifulSoup(response.text, 'html.parser')
        forms = soup.find_all('form')
        
        # --- LOGIC FIX: HANDLE JS REDIRECT ---
        # Some firewalls (like Fortinet) return a page with NO forms, just a JS redirect.
        if len(forms) == 0:
            print(">> No forms found. Checking for JavaScript Redirect...")
            # Look for patterns like: window.location="URL" or window.location.href="URL"
            match = re.search(r'window\.location\.?h?r?e?f?\s*=\s*"([^"]+)"', response.text)
            
            if match:
                redirect_url = match.group(1)
                print(f">> JS Redirect Detected! Following to: {redirect_url}")
                
                try:
                    # Recursively follow the link to find the real page
                    new_response = self.session.get(redirect_url, allow_redirects=True)
                    # Recursively analyze the NEW page
                    return self.analyze_page(new_response)
                except Exception as e:
                    print(f">> Failed to follow JS redirect: {e}")
                    return None
            else:
                print(">> No JS redirect found either.")
                return None
        # -------------------------------------

        print(f">> Found {len(forms)} forms on the page.")

        best_form = None
        highest_score = 0

        for index, form in enumerate(forms):
            # Calculate the full URL for the form action
            action_url = urljoin(response.url, form.get('action', ''))
            
            form_details = {
                "id": index,
                "action": action_url,
                "method": form.get('method', 'POST').upper(),
                "inputs": []
            }
            
            current_score = 0
            has_password = False
            
            # Find all inputs (and buttons) in this form
            all_inputs = form.find_all(['input', 'button'])
            
            for inp in all_inputs:
                name = inp.get('name')
                inp_type = inp.get('type', 'text').lower()
                value = inp.get('value', '')
                
                field_role = "unknown"
                
                # HEURISTIC 1: Password Field
                if inp_type == "password":
                    field_role = "password"
                    has_password = True
                    current_score += 10
                
                # HEURISTIC 2: Hidden Tokens (Critical for Firewalls)
                elif inp_type == "hidden":
                    field_role = "hidden"
                    current_score += 1
                
                # HEURISTIC 3: Username Field
                elif inp_type in ["text", "email"]:
                    if name and any(x in name.lower() for x in ['user', 'name', 'login', 'id', 'email', 'auth']):
                        field_role = "username"
                        current_score += 5
                    else:
                        field_role = "text"
                
                if name: 
                    form_details['inputs'].append({
                        "name": name,
                        "type": inp_type,
                        "value": value,
                        "role": field_role
                    })

            # If it has a password field, it's likely the winner
            if has_password and current_score > highest_score:
                highest_score = current_score
                best_form = form_details

        return best_form

    def login(self, form_details, username, password):
        """
        Constructs the payload and submits the form.
        """
        payload = {}
        
        print(f">> Preparing login payload for: {form_details['action']}")
        
        for inp in form_details['inputs']:
            if inp['role'] == 'username':
                payload[inp['name']] = username
            elif inp['role'] == 'password':
                payload[inp['name']] = password
            elif inp['role'] == 'hidden':
                # ALWAYS send hidden tokens back exactly as received
                payload[inp['name']] = inp['value']
            # Ignore generic text fields
            
        try:
            # Set headers to look like a real browser submission
            headers = {
                'Referer': form_details['action'],
                'Origin': self.get_portal_identifier(form_details['action'])
            }
            
            if form_details['method'] == 'POST':
                resp = self.session.post(form_details['action'], data=payload, headers=headers)
            else:
                resp = self.session.get(form_details['action'], params=payload, headers=headers)
                
            return resp
        except Exception as e:
            print(f">> Submission Error: {e}")
            return None

if __name__ == "__main__":
    # Quick Test
    solver = UniversalSolver()
    page = solver.get_portal_page()
    if page == "ONLINE":
        print("You are Online.")
    elif page:
        print("Portal Found. Analyzing...")
        form = solver.analyze_page(page)
        if form:
            print("SUCCESS: Found Login Form!")