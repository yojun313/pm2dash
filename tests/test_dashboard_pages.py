import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined


class DashboardPageTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment = Environment(
            loader=FileSystemLoader("app/templates"),
            undefined=StrictUndefined,
        )
        cls.template = cls.environment.get_template("process.html")

    def render(self, active_page: str) -> str:
        return self.template.render(
            active_page=active_page,
            page_title="Test page",
            page_description="Test description",
            processes=[],
        )

    def test_overview_only_renders_navigation_cards(self):
        html = self.render("overview")

        self.assertIn("관리할 영역을 선택하세요.", html)
        self.assertNotIn('id="server-overview"', html)
        self.assertNotIn('id="aiUsageChart"', html)
        self.assertNotIn('id="pm2-list-body"', html)

    def test_server_page_renders_resources_and_processes(self):
        html = self.render("server")

        self.assertIn('id="server-overview"', html)
        self.assertIn('id="srvCpuText"', html)
        self.assertIn('id="pm2-list-body"', html)
        self.assertIn('id="logModal"', html)
        self.assertNotIn('id="aiUsageChart"', html)

    def test_ai_page_only_renders_ai_usage(self):
        html = self.render("ai_usage")

        self.assertIn('id="aiUsageChart"', html)
        self.assertIn("/api/ai-usage?days=7", html)
        self.assertNotIn('id="server-overview"', html)
        self.assertNotIn('id="pm2-list-body"', html)

if __name__ == "__main__":
    unittest.main()
