"""Flask workflow smoke tests; run after installing requirements.txt."""
import re
import unittest

try:
    from flask import Flask
    from app import app
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False


@unittest.skipUnless(FLASK_AVAILABLE, "Install requirements.txt to run Flask route tests")
class File2BaseWebTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = app.test_client()

    @staticmethod
    def token(html: str) -> str:
        match = re.search(r'name="_csrf_token" value="([^"]+)"', html)
        if not match:
            raise AssertionError("CSRF token was not rendered in the form")
        return match.group(1)

    def test_health_and_csrf_rejection(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")
        rejected = self.client.post("/demo")
        self.assertEqual(rejected.status_code, 400)

    def test_demo_preflight_create_and_download_report(self):
        home = self.client.get("/")
        token = self.token(home.get_data(as_text=True))
        started = self.client.post("/demo", data={"_csrf_token": token}, follow_redirects=False)
        self.assertEqual(started.status_code, 302)
        review_url = started.headers["Location"]
        review_page = self.client.get(review_url)
        review_html = review_page.get_data(as_text=True)
        self.assertEqual(review_page.status_code, 200)
        self.assertIn("Review schema", review_html)
        token = self.token(review_html)
        workspace_id = re.search(r"/review/([0-9a-f]{32})", review_url).group(1)

        preflight_response = self.client.post(
            f"/preflight/{workspace_id}",
            data={"_csrf_token": token},
            follow_redirects=False,
        )
        self.assertEqual(preflight_response.status_code, 302)
        preflight_page = self.client.get(preflight_response.headers["Location"])
        preflight_html = preflight_page.get_data(as_text=True)
        self.assertEqual(preflight_page.status_code, 200)
        self.assertIn("No blocking issues found", preflight_html)
        token = self.token(preflight_html)

        created = self.client.post(
            f"/create/{workspace_id}",
            data={"_csrf_token": token, "confirm_migration": "yes"},
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 302)
        database_page = self.client.get(created.headers["Location"])
        self.assertEqual(database_page.status_code, 200)
        self.assertIn("Your database is ready", database_page.get_data(as_text=True))
        report = self.client.get(f"/report/{workspace_id}")
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.get_json()["status"], "success")


if __name__ == "__main__":
    unittest.main()
