import requests
from bs4 import BeautifulSoup
from mcp_gateway.security_scanner.config import URLS
from mcp_gateway.security_scanner.config import Keys
import logging

logger = logging.getLogger(__name__)


class SmitheryFetcher:
    def __init__(self, project_name: str):
        self.project_name = project_name

    def fetch(self):
        """
        Fetch the HTML content from Smithery.

        Returns:
            str: The HTML content from the Smithery page

        Raises:
            requests.RequestException: If the HTTP request fails
        """
        url = URLS.SMITHERY.format(project_name=self.project_name)
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.error(
                f"Failed to fetch data from Smithery for {self.project_name}: {e}"
            )
            raise

    def get_mcp_data(self):
        """
        Extract MCP data from the Smithery HTML page.

        Returns:
            Dict[str, Any]: Dictionary containing the extracted MCP data

        Raises:
            Exception: If HTML parsing fails or required elements are not found
        """
        try:
            data = self.fetch()
            soup = BeautifulSoup(data, "html.parser")
            main_content = soup.find("main")

            if not main_content:
                logger.error(
                    f"Could not find main content on Smithery page for {self.project_name}"
                )
                raise ValueError("Main content not found on Smithery page")

            # Extract GitHub link with null check
            github_link = main_content.find("a", title=True)
            github_link_url = github_link["href"] if github_link else None

            if not github_link_url:
                logger.warning(f"No GitHub link found for {self.project_name}")

            # Extract verification status
            verified = bool(main_content.find("svg", {"class": "lucide-badge-check"}))

            # Extract project details
            project_details = main_content.find("div", {"class": "space-y-6 mt-4"})

            # Extract license with null checks
            mcp_license = None
            if project_details:
                license_heading = project_details.find("h3", string="License")
                if license_heading:
                    license_sibling = license_heading.find_next_sibling("span")
                    mcp_license = license_sibling.text if license_sibling else None

            # Extract monthly tool usage with null checks
            monthly_tool_usage = 0
            if project_details:
                monthly_tool_calls_heading = project_details.find(
                    "h3", string="Monthly Tool Calls"
                )
                if monthly_tool_calls_heading:
                    usage_div = monthly_tool_calls_heading.find_next_sibling("div")
                    if usage_div:
                        usage_span = usage_div.find("span")
                        if usage_span and usage_span.text:
                            try:
                                monthly_tool_usage = int(
                                    usage_span.text.replace(",", "")
                                )
                            except ValueError:
                                logger.warning(
                                    f"Could not parse monthly tool usage: {usage_span.text}"
                                )
                                monthly_tool_usage = 0

            # Extract running local status
            running_local = None
            if project_details:
                local_heading = project_details.find("h3", string="Local")
                if local_heading:
                    local_sibling = local_heading.find_next_sibling("span")
                    running_local = local_sibling.text if local_sibling else None

            # Extract published date
            published_at = None
            if project_details:
                published_heading = project_details.find("h3", string="Published")
                if published_heading:
                    published_sibling = published_heading.find_next_sibling("span")
                    published_at = published_sibling.text if published_sibling else None

            result = {
                Keys.GITHUB_LINK: github_link_url,
                Keys.VERIFIED: verified,
                Keys.LICENSE: mcp_license,
                Keys.MONTHLY_TOOL_USAGE: monthly_tool_usage,
                Keys.RUNNING_LOCAL: running_local,
                Keys.PUBLISHED_AT: published_at,
            }

            logger.debug(
                f"Successfully extracted MCP data for {self.project_name}: {result}"
            )
            return result

        except Exception as e:
            logger.error(f"Error extracting MCP data for {self.project_name}: {e}")
            raise


if __name__ == "__main__":
    fetcher = SmitheryFetcher("@barlanyado/test123")
    print(fetcher.get_mcp_data())
