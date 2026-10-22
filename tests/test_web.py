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


    def test_landing_design_motion_and_navigation_features(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="section-prev"', html)
        self.assertIn('id="section-next"', html)
        self.assertIn('href="#mvp" data-section="mvp"', html)
        self.assertIn('href="#vision" data-section="vision"', html)
        self.assertIn('<span>sale_date</span>', html)
        self.assertIn('class="lp-profiled"', html)
        self.assertIn('img/file2base-mark.svg', html)

        js_url = re.search(r'src="([^"]*landing\.js)"', html).group(1)
        res_js = self.client.get(js_url)
        js = res_js.get_data(as_text=True)
        res_js.close()
        self.assertIn('updateStepFromScroll', js)
        self.assertIn('scheduleNextSchemaStage', js)
        self.assertIn('updateVisionParallax', js)
        self.assertIn("section-prev", js)

        css_url = re.search(r'href="([^"]*landing\.css)"', html).group(1)
        res_css = self.client.get(css_url)
        css = res_css.get_data(as_text=True)
        res_css.close()
        self.assertIn('@keyframes lp-flow-dash', css)
        self.assertIn('.lp-roadmap-line.is-inview:after', css)
        self.assertIn('.lp-scatter:not(.is-inview) .lp-file-1', css)

        favicon = self.client.get('/static/img/file2base-mark.svg')
        self.assertEqual(favicon.status_code, 200)
        self.assertIn('<svg', favicon.get_data(as_text=True))
        favicon.close()

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
        database_html = database_page.get_data(as_text=True)
        self.assertIn("Your database is ready", database_html)
        self.assertIn("Business Overview", database_html)
        self.assertIn("Database Manager", database_html)
        self.assertIn("view-business", database_html)
        self.assertIn("view-manager", database_html)
        report = self.client.get(f"/report/{workspace_id}")
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.get_json()["status"], "success")
        report.close()


if __name__ == "__main__":
    unittest.main()
