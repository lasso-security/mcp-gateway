import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from mcp_gateway.security_scanner.config import Keys
import requests

logger = logging.getLogger(__name__)


class NPMCollector:
    """
    Collects and processes package information from the npm registry.

    Attributes:
        package_name (str): The name of the npm package.
        _raw_data (Optional[Dict[str, Any]]): Raw data fetched from the npm registry.
        _download_stats (Optional[Dict[str, Any]]): Download statistics for the package.
    """

    _NPM_REGISTRY_URL = "https://registry.npmjs.org"
    _NPM_DOWNLOADS_API_URL = "https://api.npmjs.org/downloads/point"

    def __init__(self, package_name: str) -> None:
        """
        Initializes the NPMCollector with a package name.

        Args:
            package_name: The name of the npm package to collect data for.
        """
        self.original_package_name: str = package_name
        self.package_name: str = self._parse_package_name(package_name)
        self.version_tag: Optional[str] = self._extract_version_tag(package_name)
        self._raw_data: Optional[Dict[str, Any]] = None
        self._download_stats: Optional[Dict[str, Any]] = None

    def _parse_package_name(self, package_name: str) -> str:
        """
        Parses the package name to remove version tags.

        Examples:
            - "@upstash/context7-mcp@latest" -> "@upstash/context7-mcp"
            - "express@4.18.2" -> "express"
            - "@angular/core@16.0.0" -> "@angular/core"

        Args:
            package_name: The raw package name potentially with version tag

        Returns:
            The clean package name without version tag
        """
        package_name = package_name.strip()

        # Handle scoped packages (e.g., @scope/package@version)
        if package_name.startswith("@"):
            # Find the last @ symbol, which should be the version separator
            # We need to be careful because scoped packages already have one @
            parts = package_name.split("@")
            if len(parts) > 2:  # @scope/package@version has 3 parts when split by @
                # Reconstruct without the version: @scope/package
                return "@" + "@".join(parts[1:-1])
            else:
                # No version tag, return as-is
                return package_name.lower()
        else:
            # Handle regular packages (e.g., package@version)
            if "@" in package_name:
                return package_name.split("@")[0].lower()
            else:
                return package_name.lower()

    def _extract_version_tag(self, package_name: str) -> Optional[str]:
        """
        Extracts the version tag from a package name.

        Args:
            package_name: The raw package name potentially with version tag

        Returns:
            The version tag if present, None otherwise
        """
        package_name = package_name.strip()

        # Handle scoped packages
        if package_name.startswith("@"):
            parts = package_name.split("@")
            if len(parts) > 2:  # @scope/package@version
                return parts[-1]  # Return the last part as version
        else:
            # Handle regular packages
            if "@" in package_name:
                return package_name.split("@")[-1]

        return None

    def _fetch_json(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Synchronously fetches JSON data from a given URL using requests.

        Args:
            url: The URL to fetch data from.

        Returns:
            A dictionary containing the JSON response, or None if an error occurs.
        """
        logger.debug(f"Fetching data from {url}")
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
            data = response.json()
            logger.debug(f"Successfully fetched data from {url}")
            return data
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching data from {url}: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred while fetching {url}: {e}")
        return None

    def fetch_data(self) -> bool:
        """
        Fetches all required data from the npm registry and downloads API synchronously.

        This method populates `_raw_data` and `_download_stats`.

        Returns:
            True if all data was fetched successfully, False otherwise.
        """
        if not self.package_name:
            logger.error("Package name is not set.")
            return False

        package_url = f"{self._NPM_REGISTRY_URL}/{self.package_name}"
        downloads_url = f"{self._NPM_DOWNLOADS_API_URL}/last-month/{self.package_name}"

        self._raw_data = self._fetch_json(package_url)
        self._download_stats = self._fetch_json(downloads_url)

        if self._raw_data and "error" in self._raw_data:
            logger.error(
                f"Error from NPM registry for {self.package_name}: {self._raw_data['error']}"
            )
            self._raw_data = None
            return False

        if self._download_stats and "error" in self._download_stats:
            logger.warning(
                f"Error from NPM downloads API for {self.package_name}: {self._download_stats['error']}"
            )

        return bool(self._raw_data)

    def _get_from_raw(self, path: List[str], default: Any = None) -> Any:
        """
        Safely retrieves a nested value from the _raw_data dictionary.

        Args:
            path: A list of keys representing the path to the desired value.
            default: The value to return if the path is not found.

        Returns:
            The retrieved value or the default.
        """
        if self._raw_data is None:
            return default
        current = self._raw_data
        for key in path:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current

    @property
    def description(self) -> Optional[str]:
        """str: The package description. Returns None if not available."""
        return self._get_from_raw(["description"])

    @property
    def github_url(self) -> Optional[str]:
        """str: The GitHub repository URL for the package. Returns None if not available or not a GitHub URL."""
        repo_info = self._get_from_raw(["repository"])
        if isinstance(repo_info, dict) and "url" in repo_info:
            url = repo_info["url"]
            if isinstance(url, str):
                # Standardize git URLs (git+https://, git://, etc.) to https://
                match = re.search(
                    r"(?:git\+ssh:\/\/git@|git\+https:\/\/|git:\/\/|github:)([\w.-]+)\/([\w.-]+?)(?:\.git)?$",
                    url,
                )
                if match:
                    user, repo = match.groups()
                    return f"https://github.com/{user}/{repo}"
                # Handle direct https URLs specifically for GitHub
                if url.startswith("https://github.com/"):
                    # Ensure .git is removed if present at the end
                    return url.removesuffix(".git")
        homepage = self.homepage_url
        if homepage and "github.com" in homepage:
            return homepage.removesuffix(".git")
        issues_url = self.bug_tracker_url
        if issues_url and "github.com" in issues_url:
            return issues_url.removesuffix("/issues")
            # Fallback for other URL structures that might be GitHub, simple check
        return None

    @property
    def downloads_last_month(self) -> Optional[int]:
        """int: The number of downloads in the last month. Returns None if not available."""
        if self._download_stats and isinstance(
            self._download_stats.get("downloads"), int
        ):
            return self._download_stats["downloads"]
        return None

    @property
    def num_versions(self) -> Optional[int]:
        """int: The total number of published versions. Returns None if not available."""
        versions = self._get_from_raw(["versions"])
        if isinstance(versions, dict):
            return len(versions)
        return None

    @property
    def days_since_last_updated(self) -> Optional[int]:
        """int: The number of days since the last package update. Returns None if not available."""
        time_data = self._get_from_raw(["time", "modified"])
        if isinstance(time_data, str):
            try:
                # Parse ISO 8601 timestamp, handling potential Z for UTC
                last_updated = datetime.fromisoformat(time_data.replace("Z", "+00:00"))
                return (datetime.now(timezone.utc) - last_updated).days
            except ValueError:
                logger.warning(f"Could not parse last_updated timestamp: {time_data}")
        return None

    @property
    def days_since_created(self) -> Optional[int]:
        """int: The number of days since the package creation. Returns None if not available."""
        time_data = self._get_from_raw(["time", "created"])
        if isinstance(time_data, str):
            try:
                created_at_dt = datetime.fromisoformat(time_data.replace("Z", "+00:00"))
                return (datetime.now(timezone.utc) - created_at_dt).days
            except ValueError:
                logger.warning(f"Could not parse created_at timestamp: {time_data}")
        return None

    @property
    def license_info(self) -> Optional[Any]:  # Can be string or dict
        """str | Dict: License information for the package (e.g., 'MIT' or a SPDX license object).
        Returns None if not available.
        """
        return self._get_from_raw(["license"])

    @property
    def num_maintainers(self) -> Optional[int]:
        """int: The number of package maintainers. Returns None if not available."""
        maintainers = self._get_from_raw(["maintainers"])
        if isinstance(maintainers, list):
            return len(maintainers)
        return None

    @property
    def maintainers_names(self) -> Optional[List[str]]:
        """List[str]: A list of package maintainer names. Returns None if not available."""
        maintainers_data = self._get_from_raw(["maintainers"])
        if isinstance(maintainers_data, list):
            names = [
                m.get("name")
                for m in maintainers_data
                if isinstance(m, dict) and m.get("name")
            ]
            return names if names else None
        return None

    @property
    def homepage_url(self) -> Optional[str]:
        """str: The homepage URL for the package. Returns None if not available."""
        return self._get_from_raw(["homepage"])

    @property
    def bug_tracker_url(self) -> Optional[str]:
        """str: The bug tracker URL for the package. Returns None if not available."""
        bugs_info = self._get_from_raw(["bugs"])
        if isinstance(bugs_info, dict) and "url" in bugs_info:
            return bugs_info["url"]
        return None

    @property
    def keywords(self) -> Optional[List[str]]:
        """List[str]: A list of keywords associated with the package. Returns None if not available."""
        return self._get_from_raw(["keywords"])

    def get_all_data(self) -> Dict[str, Any]:
        """
        Returns a dictionary containing all collected and processed package data.
        This is useful for serialization or comprehensive review.
        """
        if not self._raw_data:
            logger.warning("Data has not been fetched yet. Call fetch_data() first.")
            return {"error": "Data not fetched. Call fetch_data() first."}

        return {
            Keys.PACKAGE_NAME: self.package_name,
            Keys.ORIGINAL_PACKAGE_NAME: self.original_package_name,
            Keys.VERSION_TAG: self.version_tag,
            Keys.DESCRIPTION: self.description,
            Keys.GITHUB_LINK: self.github_url,
            Keys.DOWNLOADS_LAST_MONTH: self.downloads_last_month,
            Keys.NUM_VERSIONS: self.num_versions,
            Keys.DAYS_SINCE_LAST_UPDATED: self.days_since_last_updated,
            Keys.DAYS_SINCE_CREATED: self.days_since_created,
            Keys.LICENSE_INFO: self.license_info,
            Keys.NUM_MAINTAINERS: self.num_maintainers,
            Keys.MAINTAINERS_NAMES: self.maintainers_names,
            Keys.HOMEPAGE_URL: self.homepage_url,
            Keys.BUG_TRACKER_URL: self.bug_tracker_url,
            Keys.KEYWORDS: self.keywords,
        }


def main_example(package_name: str) -> None:
    """Example usage of the NPMCollector."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )

    collector = NPMCollector(package_name)

    success = collector.fetch_data()

    if success:
        logger.info(f"--- Successfully fetched data for {package_name} ---")
        all_data = collector.get_all_data()
        for key, value in all_data.items():
            logger.info(f"{key.replace('_', ' ').capitalize()}: {value}")
    else:
        logger.error(f"Failed to fetch data for {package_name}.")


if __name__ == "__main__":
    main_example("@waldzellai/clear-thought")
    # main_example("nonexistentpackage123abc")
    # main_example("express")
    # main_example("@angular/core")
    # main_example("lodash")
