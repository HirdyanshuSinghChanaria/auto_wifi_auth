"""Offline unit tests for the portal HTML parsing logic."""
import unittest

from universal_solver import UniversalSolver


class FakeResponse:
    """Just enough of a requests.Response for analyze_page()."""

    def __init__(self, text, url="http://192.168.1.1/login"):
        self.text = text
        self.url = url


class TestFindRedirectUrl(unittest.TestCase):
    def setUp(self):
        self.solver = UniversalSolver()

    def test_meta_refresh_plain(self):
        html = '<meta http-equiv="refresh" content="0;url=http://portal/login">'
        self.assertEqual(self.solver.find_redirect_url(html), "http://portal/login")

    def test_meta_refresh_quoted_and_uppercase(self):
        html = "<meta http-equiv=\"REFRESH\" content=\"0; URL='http://portal/login'\">"
        self.assertEqual(self.solver.find_redirect_url(html), "http://portal/login")

    def test_meta_refresh_relative(self):
        html = '<meta http-equiv="refresh" content="0;url=login.html">'
        self.assertEqual(self.solver.find_redirect_url(html), "login.html")

    def test_js_window_location(self):
        html = '<script>window.location = "http://portal/auth";</script>'
        self.assertEqual(self.solver.find_redirect_url(html), "http://portal/auth")

    def test_js_location_replace(self):
        html = "<script>location.replace('http://portal/x')</script>"
        self.assertEqual(self.solver.find_redirect_url(html), "http://portal/x")

    def test_no_redirect(self):
        self.assertIsNone(self.solver.find_redirect_url("<html><body>hi</body></html>"))


class TestAnalyzePage(unittest.TestCase):
    def setUp(self):
        self.solver = UniversalSolver()

    def test_standard_form(self):
        html = """
        <form action="/auth" method="POST">
          <input type="hidden" name="CSRFToken" value="abc123">
          <input type="text" name="username">
          <input type="password" name="password">
        </form>
        """
        form = self.solver.analyze_page(FakeResponse(html))
        self.assertIsNotNone(form)
        self.assertEqual(form['pass_field'], 'password')
        self.assertEqual(form['user_field'], 'username')
        self.assertEqual(form['action'], '/auth')
        self.assertEqual(form['method'], 'post')
        # Hidden field names must keep their ORIGINAL case (CSRF tokens)
        self.assertIn({'name': 'CSRFToken', 'value': 'abc123'}, form['inputs'])

    def test_inputs_scoped_to_login_form(self):
        html = """
        <form action="/search">
          <input type="text" name="q">
          <input type="hidden" name="tracker" value="x">
        </form>
        <form action="/login" method="post">
          <input type="text" name="userid">
          <input type="password" name="pwd">
        </form>
        """
        form = self.solver.analyze_page(FakeResponse(html))
        self.assertEqual(form['user_field'], 'userid')
        self.assertEqual(form['action'], '/login')
        self.assertNotIn({'name': 'tracker', 'value': 'x'}, form['inputs'])

    def test_no_password_field_returns_none(self):
        html = '<form><input type="text" name="search"></form>'
        self.assertIsNone(self.solver.analyze_page(FakeResponse(html)))

    def test_unnamed_password_field_returns_none(self):
        html = '<form><input type="password"></form>'
        self.assertIsNone(self.solver.analyze_page(FakeResponse(html)))

    def test_cyberoam_orphan_inputs(self):
        html = """
        <input type="text" name="username">
        <input type="password" name="password">
        """
        url = "http://172.16.68.6:8090/httpclient.html"
        form = self.solver.analyze_page(FakeResponse(html, url=url))
        self.assertEqual(form['action'], 'login.xml')
        self.assertIn({'name': 'mode', 'value': '191'}, form['inputs'])

    def test_fallback_user_field_without_hint(self):
        html = """
        <form method="get" action="auth.cgi">
          <input type="text" name="xyz123">
          <input type="password" name="pw">
        </form>
        """
        form = self.solver.analyze_page(FakeResponse(html))
        self.assertEqual(form['user_field'], 'xyz123')
        self.assertEqual(form['method'], 'get')

    def test_empty_method_defaults_to_post(self):
        html = """
        <form action="/a" method="">
          <input type="text" name="user">
          <input type="password" name="pass">
        </form>
        """
        form = self.solver.analyze_page(FakeResponse(html))
        self.assertEqual(form['method'], 'post')

    def test_first_hint_match_wins(self):
        html = """
        <form action="/a" method="post">
          <input type="text" name="userid">
          <input type="text" name="promo_email">
          <input type="password" name="pass">
        </form>
        """
        form = self.solver.analyze_page(FakeResponse(html))
        self.assertEqual(form['user_field'], 'userid')


if __name__ == "__main__":
    unittest.main()
