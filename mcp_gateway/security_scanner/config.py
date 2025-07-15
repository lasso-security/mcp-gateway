import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Configure file logging
LOG_DIR = Path(os.path.expanduser("~/.mcp-gateway"))
LOG_DIR.mkdir(parents=True, exist_ok=True)  # Ensure the directory exists
LOG_FILE = LOG_DIR / "scanner.log"

file_handler = logging.FileHandler(LOG_FILE)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


class URLS:
    SMITHERY = "https://smithery.ai/server/{project_name}"
    GITHUB = "https://github.com/{owner}/{project_name}"


class MarketPlaces:
    SMITHERY = "smithery"
    NPM = "npm"


class Keys:
    # Top-level metadata keys returned by Collector
    PROJECT_METADATA = "project_metadata"
    GITHUB_REPO_METADATA = "github_repo_metadata"
    GITHUB_OWNER_METADATA = "github_owner_metadata"
    EMAIL = "email"
    BLOG = "blog"

    # Smithery specific keys
    GITHUB_LINK = "github_link"
    VERIFIED = "verified"  # Used in both Smithery and GitHub Owner
    IS_VERIFIED = "is_verified"
    LICENSE = "license"  # Used in both Smithery and GitHub Repo
    MONTHLY_TOOL_USAGE = "monthly_tool_usage"
    RUNNING_LOCAL = "running_local"
    PUBLISHED_AT = "published_at"

    # GitHub Repo specific keys
    STARS = "stars"
    STARGAZERS_COUNT = "stargazers_count"
    FORKS = "forks"
    UPDATED_AT = "updated_at"
    CREATED_AT = "created_at"

    # GitHub Owner specific keys
    FOLLOWERS = "followers"
    PUBLIC_REPOS_NUMBER = "public_repos_number"
    PUBLIC_REPOS = "public_repos"
    OWNER_TYPE = "owner_type"
    TYPE = "type"
    LOCATION = "location"
    NAME = "name"  # Also used for license fallback
    TWITTER_USERNAME = "twitter_username"
    LOGIN = "login"

    # NPM Collector specific keys (some might overlap if semantics are identical)
    PACKAGE_NAME = "package_name"
    ORIGINAL_PACKAGE_NAME = "original_package_name"  # Package name with version tag
    VERSION_TAG = "version_tag"
    DESCRIPTION = "description"
    DOWNLOADS_LAST_MONTH = "downloads_last_month"
    NUM_VERSIONS = "num_versions"
    DAYS_SINCE_LAST_UPDATED = "days_since_last_updated"
    DAYS_SINCE_CREATED = (
        "days_since_created"  # Specifically for NPM package creation delta in days
    )
    LICENSE_INFO = "license_info"  # For the potentially complex license object from NPM
    NUM_MAINTAINERS = "num_maintainers"
    MAINTAINERS_NAMES = "maintainers_names"
    HOMEPAGE_URL = "homepage_url"
    BUG_TRACKER_URL = "bug_tracker_url"
    KEYWORDS = "keywords"
    ERROR = "error"  # For error messages

    # Score component keys used in ProjectAnalyzer
    OWNER_SCORE = "owner_score"
    REPO_SCORE = "repo_score"
    PROJECT_SCORE = (
        "project_score"  # Key for the main project score (e.g., NPM's combined score)
    )
    SOURCE_SCORE = "source_score"  # Key for a marketplace-specific data score component
    SMITHERY_SCORE = "smithery_score"  # Specific key for Smithery score, also used in the error fallback logic

    # Specific Values
    ORGANIZATION_OWNER_TYPE = "Organization"


# License Constants
PERMISSIVE_LICENSES = {"mit", "apache-2.0", "bsd-3-clause", "isc"}

TRUSTED_ORGANIZATION_NAMES = [
    "lasso-security",
    "smithery-ai",
    "aws",
    "google",
    "microsoft",
    "apple",
    "facebook",
    "twitter",
    "github",
    "gitlab",
    "bitbucket",
]
