import requests
import logging
from mcp_gateway.security_scanner.config import Keys

logger = logging.getLogger(__name__)


class GithubFetcher:
    def __init__(self, url: str):
        """
        Initialize the GitHub fetcher with a GitHub URL.

        Args:
            url: The GitHub repository URL

        Raises:
            ValueError: If the URL is invalid or not a GitHub URL
        """
        if not url:
            raise ValueError("GitHub URL cannot be empty")

        self.url = url
        self.repository_name = None
        self.owner = None

        # Parse the GitHub URL
        try:
            self._parse_github_url(url)
        except Exception as e:
            logger.error(f"Failed to parse GitHub URL {url}: {e}")
            raise ValueError(f"Invalid GitHub URL format: {url}")

    def _parse_github_url(self, url: str) -> None:
        """
        Parse the GitHub URL to extract owner and repository name.

        Args:
            url: The GitHub URL to parse

        Raises:
            ValueError: If the URL format is invalid
        """
        if "github.com" not in url:
            raise ValueError("URL must be a GitHub URL")

        # Remove common URL prefixes and suffixes
        clean_url = url.replace("https://github.com/", "").replace(
            "http://github.com/", ""
        )
        clean_url = clean_url.rstrip("/")

        # Handle various GitHub URL formats
        if clean_url.endswith(".git"):
            clean_url = clean_url[:-4]

        # Split by / and handle tree/main or other path components
        parts = clean_url.split("/")

        if len(parts) < 2:
            raise ValueError("GitHub URL must contain owner and repository")

        self.owner = parts[0]
        self.repository_name = parts[1]

        # Validate the extracted components
        if not self.owner or not self.repository_name:
            raise ValueError("Could not extract owner and repository from URL")

        logger.debug(
            f"Parsed GitHub URL: owner={self.owner}, repo={self.repository_name}"
        )

    def get_repository_metadata(self) -> dict:
        """
        Fetch repository metadata from GitHub API.

        Returns:
            dict: Repository metadata or None if fetch fails
        """
        try:
            repository_api_url = (
                f"https://api.github.com/repos/{self.owner}/{self.repository_name}"
            )
            logger.debug(f"Fetching repository metadata from: {repository_api_url}")

            response = requests.get(repository_api_url, timeout=10)
            response.raise_for_status()

            repo_data = response.json()

            # Extract repository information
            stars = repo_data.get(Keys.STARGAZERS_COUNT, 0)
            forks = repo_data.get(Keys.FORKS, 0)
            updated_at = repo_data.get(Keys.UPDATED_AT)
            created_at = repo_data.get(Keys.CREATED_AT)

            # Handle license information
            license_info = repo_data.get(Keys.LICENSE, {})
            github_license_key = None

            if license_info and isinstance(license_info, dict):
                license_key = license_info.get(Keys.LICENSE)
                if license_key and license_key != "other":
                    github_license_key = license_key
                else:
                    github_license_key = license_info.get(Keys.NAME)

            result = {
                Keys.STARS: stars,
                Keys.FORKS: forks,
                Keys.LICENSE: github_license_key,
                Keys.UPDATED_AT: updated_at,
                Keys.CREATED_AT: created_at,
            }

            logger.debug(
                f"Successfully fetched repository metadata for {self.owner}/{self.repository_name}"
            )
            return result

        except requests.RequestException as e:
            logger.error(
                f"Error fetching repository metadata for {self.owner}/{self.repository_name}: {e}"
            )
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching repository metadata: {e}")
            return None

    def get_owner_metadata(self) -> dict:
        """
        Fetch owner metadata from GitHub API.

        Returns:
            dict: Owner metadata or None if fetch fails
        """
        try:
            # Try organization endpoint first
            organization_api_url = f"https://api.github.com/orgs/{self.owner}"
            logger.debug(f"Trying organization API: {organization_api_url}")

            owner_response = requests.get(organization_api_url, timeout=10)

            if owner_response.status_code != 200:
                # Try user endpoint if organization fails
                user_api_url = f"https://api.github.com/users/{self.owner}"
                logger.debug(f"Trying user API: {user_api_url}")
                owner_response = requests.get(user_api_url, timeout=10)

            owner_response.raise_for_status()
            owner_data = owner_response.json()

            # Extract owner information
            owner_type = owner_data.get(Keys.TYPE, "Unknown")
            followers = owner_data.get(Keys.FOLLOWERS, 0)
            public_repos_number = owner_data.get(Keys.PUBLIC_REPOS, 0)
            verified = owner_data.get(Keys.IS_VERIFIED, False)
            blog = owner_data.get(Keys.BLOG, None)
            email = owner_data.get(Keys.EMAIL, None)
            location = owner_data.get(Keys.LOCATION, None)
            created_at = owner_data.get(Keys.CREATED_AT, None)
            twitter_username = owner_data.get(Keys.TWITTER_USERNAME, None)

            result = {
                Keys.FOLLOWERS: followers,
                Keys.VERIFIED: verified,
                Keys.PUBLIC_REPOS_NUMBER: public_repos_number,
                Keys.OWNER_TYPE: owner_type,
                Keys.BLOG: blog,
                Keys.EMAIL: email,
                Keys.LOCATION: location,
                Keys.CREATED_AT: created_at,
                Keys.TWITTER_USERNAME: twitter_username,
            }

            logger.debug(f"Successfully fetched owner metadata for {self.owner}")
            return result

        except requests.RequestException as e:
            logger.error(f"Error fetching owner metadata for {self.owner}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching owner metadata: {e}")
            return None

    def get_repository_data(self) -> list:
        """
        Fetch both repository and owner metadata.

        Returns:
            list: [repository_metadata, owner_metadata]
        """
        repo_metadata = self.get_repository_metadata()
        owner_metadata = self.get_owner_metadata()
        return [repo_metadata, owner_metadata]


if __name__ == "__main__":
    # Example usage
    try:
        fetcher = GithubFetcher("https://github.com/lasso-security/litellm")
        print(fetcher.get_repository_data())
    except ValueError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")
