import requests
import re
import urllib3
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

# Suppress annoying InsecureRequestWarning for self-signed portal certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Common username field name hints across various captive portals
USERNAME_HINTS = {'user', 'login', 'id', 'email', 'mobile', 'phone', 'roll', 'enroll', 'name', 'uid'}

class UniversalSolver:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        })

    def find_redirect_url(self, html_content):
        """
        Hunts for hidden JavaScript or Meta redirects that Python usually misses.
        """
        # 1. Check for Meta Refresh (e.g., <meta http-equiv="refresh" content="0;url=...">)
        soup = BeautifulSoup(html_content, 'html.parser')
        meta = soup.find('meta', attrs={'http-equiv': re.compile("refresh", re.I)})
        if meta:
            content = meta.get('content', '')
            if 'url=' in content.lower():
                return content.split('url=')[-1].strip()

        # 2. Check for JavaScript redirects (window.location = ...)
        patterns = [
            r'window\.location\s*=\s*[\'\"](.*?)[\'\"]',
            r'location\.href\s*=\s*[\'\"](.*?)[\'\"]',
            r'location\.replace\([\'\"](.*?)[\'\"]\)',
            r'window\.open\([\'\"](.*?)[\'\"]\)'
        ]
        for pattern in patterns:
            match = re.search(pattern, html_content)
            if match:
                return match.group(1)
        
        return None

    def get_portal_page(self):
        """
        Probes the network and specifically handles the 'Loop' issue.
        """
        # We use a standard HTTP probe
        probe_url = "http://www.msftconnecttest.com/connecttest.txt"
        
        try:
            response = self.session.get(probe_url, timeout=5, allow_redirects=True, verify=False)
            
            # If we see "Microsoft Connect Test", we are online.
            if "Microsoft Connect Test" in response.text:
                return None 

            # CRITICAL: If we are stuck on the Microsoft URL, look for a hidden redirect
            if "msftconnecttest" in response.url:
                print(">> Stuck on 'Loading' page. Hunting for real login link...")
                real_url = self.find_redirect_url(response.text)
                
                if real_url:
                    print(f">> Found hidden redirect! Jumping to: {real_url}")
                    # Recursively get the real page
                    return self.session.get(real_url, verify=False)
                
                # Fix 1: Could not resolve the portal. Return None and surface the UI gracefully.
                print(">> No redirect found. Could not locate login portal.")
                return None

            return response
        except (requests.RequestException, requests.Timeout) as e:
            # Fix 8: Catch specific exceptions instead of bare except
            print(f">> Network probe error: {e}")
            return None

    def get_portal_identifier(self, url):
        return urlparse(url).netloc

    def analyze_page(self, response):
        """
        YOUR CONDITIONAL LOGIC IMPLEMENTATION.
        Instead of scoring, we just check each input and decide what to do.
        """
        soup = BeautifulSoup(response.text, 'html.parser')
        
        form_details = {
            'action': "",
            'method': "post",
            'inputs': [],
            'user_field': None,
            'pass_field': None,
            'page_url': response.url
        }

        # 1. Hunt for Password Field (Must exist)
        pass_input = soup.find('input', {'type': 'password'})
        if not pass_input:
            print(">> Still no password field. Dumping HTML to debug...")
            # print(response.text[:200]) # Uncomment to see what page we are actually on
            return None
        
        form_details['pass_field'] = pass_input.get('name')

        # 2. Loop through ALL inputs and apply Conditional Logic
        all_inputs = soup.find_all('input')
        
        for inp in all_inputs:
            name = inp.get('name', '').lower()
            typ = inp.get('type', 'text').lower()
            val = inp.get('value', '')

            if not name: continue

            # Condition: If it's a hidden token, keep it.
            if typ == 'hidden':
                form_details['inputs'].append({'name': name, 'value': val})
            
            # Fix 5: Widen username field detection to cover more portal types
            elif typ == 'text' or typ == 'email':
                if any(hint in name for hint in USERNAME_HINTS):
                    form_details['user_field'] = inp.get('name')

        # 3. Handle the 'Action' (Where to submit)
        # First, try to find the parent form
        parent = pass_input.find_parent('form')
        if parent:
            form_details['action'] = parent.get('action') or ""
            form_details['method'] = parent.get('method', 'post').lower()
        else:
            # Condition: If orphan inputs (Cyberoam/Sophos), force login.xml
            print(">> Orphan inputs detected. Forcing standard actions.")
            if "httpclient.html" in response.url:
                 form_details['action'] = "login.xml"
                 # Cyberoam specific patch
                 if not any(x['name'] == 'mode' for x in form_details['inputs']):
                     form_details['inputs'].append({'name': 'mode', 'value': '191'})

        return form_details

    def login(self, form_details, username, password):
        if not form_details or not form_details['pass_field']:
            return None

        # Prepare Payload
        payload = {}
        if form_details['user_field']:
            payload[form_details['user_field']] = username
        payload[form_details['pass_field']] = password
        
        for inp in form_details['inputs']:
            payload[inp['name']] = inp['value']

        target_url = urljoin(form_details['page_url'], form_details['action'])
        print(f">> Logging in to: {target_url}")

        try:
            if form_details['method'] == 'post':
                return self.session.post(target_url, data=payload, verify=False)
            else:
                return self.session.get(target_url, params=payload, verify=False)
        except (requests.RequestException, requests.Timeout) as e:
            # Fix 8: Catch specific exceptions instead of bare except
            print(f"Login Error: {e}")
            return None