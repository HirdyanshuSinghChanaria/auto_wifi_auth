import logging
import re
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup

from network_manager import PROBE_EXPECTED_TEXT, PROBE_URL

log = logging.getLogger(__name__)

# Suppress annoying InsecureRequestWarning for self-signed portal certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Common username field name hints across various captive portals
USERNAME_HINTS = {'user', 'login', 'id', 'email', 'mobile', 'phone', 'roll', 'enroll', 'name', 'uid'}

# Input types that may hold a username
TEXTLIKE_TYPES = {'text', 'email', 'tel', 'number'}

REQUEST_TIMEOUT = 10


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
        May return a RELATIVE url — callers must resolve it against the page url.
        """
        # 1. Check for Meta Refresh (e.g., <meta http-equiv="refresh" content="0;url=...">)
        soup = BeautifulSoup(html_content, 'html.parser')
        meta = soup.find('meta', attrs={'http-equiv': re.compile("refresh", re.I)})
        if meta:
            content = meta.get('content', '')
            # Case-insensitive, tolerates url='...' / url="..." quoting
            match = re.search(r"url\s*=\s*['\"]?([^'\"\s;]+)", content, re.I)
            if match:
                return match.group(1)

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
        Returns the portal login page response, or None (online / portal not found).
        """
        try:
            response = self.session.get(PROBE_URL, timeout=5, allow_redirects=True, verify=False)

            # Unmodified probe body means we are online.
            if PROBE_EXPECTED_TEXT in response.text:
                return None

            # CRITICAL: If we are stuck on the probe URL, the portal injected
            # content instead of redirecting — look for a hidden redirect.
            if urlparse(response.url).netloc == urlparse(PROBE_URL).netloc:
                log.info("Stuck on 'Loading' page. Hunting for real login link...")
                real_url = self.find_redirect_url(response.text)

                if real_url:
                    # Redirect targets are often relative — resolve against
                    # the page we found them on or requests raises MissingSchema.
                    real_url = urljoin(response.url, real_url)
                    log.info("Found hidden redirect! Jumping to: %s", real_url)
                    return self.session.get(real_url, timeout=REQUEST_TIMEOUT, verify=False)

                log.info("No redirect found. Could not locate login portal.")
                return None

            return response
        except requests.RequestException as e:
            log.warning("Network probe error: %s", e)
            return None

    def get_portal_identifier(self, url):
        return urlparse(url).netloc

    def analyze_page(self, response):
        """
        Conditional-logic form analysis: inspect each input and decide what to do.
        Returns a form-details dict, or None if no usable login form exists.
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

        # 1. Hunt for Password Field (Must exist and be submittable)
        pass_input = soup.find('input', {'type': 'password'})
        if not pass_input:
            log.warning("No password field found on portal page.")
            return None

        form_details['pass_field'] = pass_input.get('name')
        if not form_details['pass_field']:
            log.warning("Password field has no 'name' attribute — cannot submit.")
            return None

        # 2. Scope the input scan to the password field's own form when there
        # is one, so hidden tokens and text fields from unrelated forms
        # (search bars, trackers) don't leak into the login payload.
        parent_form = pass_input.find_parent('form')
        scope = parent_form if parent_form else soup

        fallback_user_field = None
        for inp in scope.find_all('input'):
            name = inp.get('name')
            if not name:
                continue
            typ = (inp.get('type') or 'text').lower()

            # Condition: If it's a hidden token, keep it — with its ORIGINAL
            # case. Servers with case-sensitive parameter names (CSRF tokens
            # especially) reject lowercased field names.
            if typ == 'hidden':
                form_details['inputs'].append({'name': name, 'value': inp.get('value', '')})

            elif typ in TEXTLIKE_TYPES:
                if fallback_user_field is None:
                    fallback_user_field = name
                # First hint match wins — it's usually the real username field
                if not form_details['user_field'] and any(hint in name.lower() for hint in USERNAME_HINTS):
                    form_details['user_field'] = name

        # No hint matched: in a form that has a password field, the first
        # text-like input is almost always the username.
        if not form_details['user_field']:
            form_details['user_field'] = fallback_user_field

        # 3. Handle the 'Action' (Where to submit)
        if parent_form:
            form_details['action'] = parent_form.get('action') or ""
            # 'or post' also covers method="" — an empty string must not
            # silently downgrade the submit to GET
            form_details['method'] = (parent_form.get('method') or 'post').lower()
        else:
            # Condition: If orphan inputs (Cyberoam/Sophos), force login.xml
            log.info("Orphan inputs detected. Forcing standard actions.")
            if "httpclient.html" in response.url:
                form_details['action'] = "login.xml"
                # Cyberoam specific patch
                if not any(x['name'] == 'mode' for x in form_details['inputs']):
                    form_details['inputs'].append({'name': 'mode', 'value': '191'})

        return form_details

    def refresh_form(self, form_details):
        """
        Stale Token Bypass: re-fetches the portal page right before login so
        hidden tokens (CSRF, session ids) are fresh — the analyzed form may be
        minutes old by the time the user finishes typing.
        Falls back to the original form if the re-fetch fails.
        """
        page_url = form_details.get('page_url')
        if not page_url:
            return form_details

        try:
            response = self.session.get(page_url, timeout=REQUEST_TIMEOUT, verify=False)
            fresh = self.analyze_page(response)
            if fresh:
                return fresh
            log.warning("Re-fetched portal page has no login form; using original tokens.")
        except requests.RequestException as e:
            log.warning("Could not refresh portal page (%s); using original tokens.", e)
        return form_details

    def login(self, form_details, username, password):
        if not form_details or not form_details.get('pass_field'):
            return None

        # Grab fresh hidden tokens right before submitting
        form_details = self.refresh_form(form_details)

        # Prepare Payload — hidden fields first so a hidden input that shares
        # a name with the user/pass fields can never overwrite the credentials
        payload = {}
        for inp in form_details.get('inputs', []):
            payload[inp['name']] = inp['value']
        if form_details.get('user_field'):
            payload[form_details['user_field']] = username
        payload[form_details['pass_field']] = password

        target_url = urljoin(form_details['page_url'], form_details.get('action', ''))
        log.info("Logging in to: %s", target_url)

        try:
            if form_details.get('method', 'post') == 'post':
                return self.session.post(target_url, data=payload, timeout=REQUEST_TIMEOUT, verify=False)
            else:
                return self.session.get(target_url, params=payload, timeout=REQUEST_TIMEOUT, verify=False)
        except requests.RequestException as e:
            log.warning("Login error: %s", e)
            return None
