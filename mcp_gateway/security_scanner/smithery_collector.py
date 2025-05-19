import requests
from bs4 import BeautifulSoup
from mcp_gateway.security_scanner.config import URLS
from mcp_gateway.security_scanner.config import Keys
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class SmitheryFetcher:
    def __init__(self, project_name: str):
        self.project_name = project_name

    def fetch(self):
        url = URLS.SMITHERY.format(project_name=self.project_name)
        response = requests.get(url)
        return response.text

    def get_mcp_data(self):
        data = self.fetch()
        soup = BeautifulSoup(data, "html.parser")
        main_content = soup.find("main")
        github_link = main_content.find("a", title=True)
        github_link_url = github_link["href"]
        verified = True if main_content.find("svg", {"class":"lucide-badge-check"}) else False
        project_details = main_content.find("div", {"class":"space-y-6 mt-4"})
        license_heading = project_details.find("h3", string="License")
        mcp_license = license_heading.find_next_sibling("span").text if license_heading else None
        monthly_tool_calls_heading = project_details.find("h3", string="Monthly Tool Calls")
        monthly_tool_usage = monthly_tool_calls_heading.find_next_sibling("div").find('span').text if monthly_tool_calls_heading else None
        monthly_tool_usage = int(monthly_tool_usage.replace(",", "")) if monthly_tool_usage else 0
        local_heading = project_details.find("h3", string="Local")
        running_local = local_heading.find_next_sibling('span').text if local_heading else None
        published_heading = project_details.find("h3", string="Published")
        published_at = published_heading.find_next_sibling('span').text if published_heading else None
        
        return {
            Keys.GITHUB_LINK: github_link_url,
            Keys.VERIFIED: verified,
            Keys.LICENSE: mcp_license,
            Keys.MONTHLY_TOOL_USAGE: monthly_tool_usage,
            Keys.RUNNING_LOCAL: running_local,
            Keys.PUBLISHED_AT: published_at,
        }


if __name__ == "__main__":
    fetcher = SmitheryFetcher("@barlanyado/test123")
    print(fetcher.get_mcp_data())
