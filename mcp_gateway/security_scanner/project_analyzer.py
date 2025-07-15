import logging
import math
from datetime import datetime, timezone
from mcp_gateway.security_scanner.config import (
    Keys,
    PERMISSIVE_LICENSES,
    MarketPlaces,
    logger,
    formatter,
)
from mcp_gateway.security_scanner.smithery_collector import SmitheryFetcher
from mcp_gateway.security_scanner.github_collector import GithubFetcher
from mcp_gateway.security_scanner.npm_collector import NPMCollector
from typing import Dict, Any, Tuple, Optional, List, Union


# Define constants for scoring (can be tuned)
OWNER_WEIGHT = 0.3
REPO_WEIGHT = 0.4
SMITHERY_WEIGHT = 0.3

# Define maximum expected values for normalization (can be adjusted based on data)
# Using log scale makes these less critical, but still useful
MAX_LOG_FOLLOWERS = 2  # log10(100)
MAX_LOG_REPOS = 2  # log10(100)
MAX_LOG_STARS = 2  # log10(100)
MAX_LOG_FORKS = 2  # log10(100)
MAX_LOG_TOOL_CALLS = 4  # log10(10k)

# For NPM Score
MAX_LOG_NPM_DOWNLOADS = 5  # log10(100,000)
MAX_LOG_NPM_VERSIONS = 2  # log10(100)
MAX_LOG_NPM_MAINTAINERS = 1  # log10(10)

NPM_REPO_WEIGHT_IN_PACKAGE_SCORE = 0.6
NPM_REGISTRY_WEIGHT_IN_PACKAGE_SCORE = 0.4


# Time decay factor (higher value means faster decay for older repos)
RECENCY_DECAY_FACTOR = 0.1
# Maximum account age in years for normalization in owner score
MAX_ACCOUNT_AGE_YEARS = 3


class ProjectAnalyzer:
    """
    Analyzes project data collected from different marketplaces and code repositories
    to calculate a reputation score.
    """

    def get_project_data(
        self, market_place: Optional[str], project_name: str
    ) -> Dict[str, Dict[str, Any]]:
        """
        Retrieves project data using the data collector.

        Returns:
            Dict[str, Dict[str, Any]]: A dictionary containing project metadata,
                                       GitHub repository metadata, and GitHub owner metadata.
        """
        logging.debug(f"Collecting data for {project_name}...")
        try:
            if market_place == MarketPlaces.SMITHERY:
                project_metadata = SmitheryFetcher(project_name).get_mcp_data()
            elif market_place == MarketPlaces.NPM:
                logger.debug(f"Collecting NPM data for {project_name}...")
                npm_collector = NPMCollector(project_name)
                npm_collector.fetch_data()
                project_metadata = npm_collector.get_all_data()
            else:
                raise ValueError(f"Market place {market_place} not supported")

            project_metadata["market_place"] = market_place

            # Handle GitHub data collection - only if GitHub link exists
            github_link = project_metadata.get(Keys.GITHUB_LINK)
            github_repo_metadata = {}
            github_owner_metadata = {}

            if github_link:
                try:
                    github_fetcher = GithubFetcher(github_link)
                    github_repo_metadata = (
                        github_fetcher.get_repository_metadata() or {}
                    )
                    github_owner_metadata = github_fetcher.get_owner_metadata() or {}
                except Exception as e:
                    logger.warning(
                        f"Could not fetch GitHub data for {github_link}: {e}"
                    )
                    # Continue without GitHub data
            else:
                logger.warning(
                    f"No GitHub link found for {project_name}, skipping GitHub data collection"
                )

            return {
                Keys.PROJECT_METADATA: project_metadata,
                Keys.GITHUB_REPO_METADATA: github_repo_metadata,
                Keys.GITHUB_OWNER_METADATA: github_owner_metadata,
            }
        except Exception as e:
            logging.error(
                f"Error collecting data for {project_name}: {e}", exc_info=True
            )
            raise

    def _normalize_log(self, value: Union[int, float], max_log_value: float) -> float:
        """Normalizes a value using log10 scale between 0 and 1."""
        if value <= 0:
            return 0.0
        log_value = math.log10(value + 1)  # Add 1 to handle zero values
        return min(log_value / max_log_value, 1.0)

    def _score_license(self, license_key: Union[str, None]) -> float:
        """Scores a license based on its type (simple example)."""
        if not license_key:
            return 0.0  # No license
        if license_key.lower() in PERMISSIVE_LICENSES:
            return 1.0
        return 0.5

    def _score_account_age(self, created_at_str: Union[str, None]) -> float:
        """Scores owner account age based on creation date."""
        if not created_at_str:
            return 0.0
        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            age_days = (now - created_at).days
            if age_days < 0:
                age_days = 0
            age_years = age_days / 365

            # Simple linear score capped at MAX_ACCOUNT_AGE_YEARS
            score = min(age_years / MAX_ACCOUNT_AGE_YEARS, 1.0)
            return max(0.0, score)
        except ValueError:
            logging.warning(f"Could not parse owner created_at date: {created_at_str}")
            return 0.0

    def _score_repo_age(self, created_at_str: Union[str, None]) -> float:
        """Scores repository age based on creation date."""
        if not created_at_str:
            return 0.0
        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            age_days = (now - created_at).days
            return self._age_score(age_days)
        except ValueError:
            logging.warning(
                f"Could not parse repository created_at date: {created_at_str}"
            )
            return 0.0

    def _calculate_owner_score(self, owner_data: Dict[str, Any]) -> float:
        """Calculates the reputation score for the owner."""
        if not owner_data:
            logging.warning("Owner data is missing, assigning zero score.")
            return 0.0

        followers_score = self._normalize_log(
            owner_data.get(Keys.FOLLOWERS, 0), MAX_LOG_FOLLOWERS
        )
        repos_score = self._normalize_log(
            owner_data.get(Keys.PUBLIC_REPOS_NUMBER, 0), MAX_LOG_REPOS
        )
        account_age_score = self._score_account_age(owner_data.get(Keys.CREATED_AT))

        verified_bonus = 0.4 if owner_data.get(Keys.VERIFIED, False) else 0.0
        org_bonus = (
            0.3
            if owner_data.get(Keys.OWNER_TYPE) == Keys.ORGANIZATION_OWNER_TYPE
            else 0.0
        )
        blog_bonus = 0.3 if owner_data.get(Keys.BLOG) else 0.0
        twitter_bonus = 0.2 if owner_data.get(Keys.TWITTER_USERNAME) else 0.0
        owner_bonus = verified_bonus + org_bonus + blog_bonus + twitter_bonus
        # Weighted average of components (weights can be tuned)
        # Adjusted weights to incorporate account age and blog
        score = (
            0.2 * followers_score
            + 0.2 * repos_score
            + 0.1 * account_age_score  # Added account age
            + 0.5 * owner_bonus  # Combine bonuses
        )
        # Ensure score is capped at 1.0 before applying main weight
        score = min(score, 1.0)
        logging.info(
            f"Owner Score details: Value: {score:.2f} (Followers: {followers_score:.2f}, Repos: {repos_score:.2f}, Age: {account_age_score:.2f}, Verified: {verified_bonus:.2f}, Org: {org_bonus:.2f}, Blog: {blog_bonus:.2f})"
        )
        return score * 100  # Scale to 0-100

    def _calculate_repo_score(self, repo_data: Dict[str, Any]) -> float:
        """Calculates the reputation score for the repository."""
        if not repo_data:
            logging.warning("Repo data is missing, assigning zero score.")
            return 0.0

        stars_score = self._normalize_log(repo_data.get(Keys.STARS, 0), MAX_LOG_STARS)
        forks_score = self._normalize_log(repo_data.get(Keys.FORKS, 0), MAX_LOG_FORKS)
        license_score = self._score_license(repo_data.get(Keys.LICENSE))
        repo_age_score = self._score_repo_age(repo_data.get(Keys.CREATED_AT))
        # Weighted average (weights can be tuned)
        score = (
            0.4 * stars_score
            + 0.3 * forks_score
            + 0.1 * license_score
            + 0.1 * repo_age_score
        )
        # Ensure score is capped at 1.0 before applying main weight
        score = min(score, 1.0)
        logger.info(
            f"Repo Score: {score:.2f} (Stars: {stars_score:.2f}, Forks: {forks_score:.2f}, License: {license_score:.2f}, Age: {repo_age_score:.2f})"
        )
        return score * 100  # Scale to 0-100

    def _calculate_smithery_score(self, project_data: Dict[str, Any]) -> float:
        """Calculates the reputation score for the Smithery project listing."""
        if not project_data:
            logging.warning("Smithery project data is missing, assigning zero score.")
            return 0.0
        logging.info(f"Project data: {project_data}")
        tool_calls_score = self._normalize_log(
            project_data.get(Keys.MONTHLY_TOOL_USAGE, 0), MAX_LOG_TOOL_CALLS
        )
        verified_bonus = 0.7 if project_data.get(Keys.VERIFIED, False) else 0.0
        license_bonus = 0.3 if project_data.get(Keys.LICENSE) else 0.0

        # Weighted average (weights can be tuned)
        score = (
            0.3 * tool_calls_score
            + 0.7 * (verified_bonus + license_bonus)  # Combine bonuses
        )
        # Ensure score is capped at 1.0 before applying main weight
        score = min(score, 1.0)
        logging.debug(
            f"Smithery Score: {score:.2f} (ToolCalls: {tool_calls_score:.2f}, Verified: {verified_bonus:.2f}, LicenseMatch: {license_bonus:.2f})"
        )
        return score * 100  # Scale to 0-100

    def _calculate_npm_score(self, project_data: Dict[str, Any]) -> float:
        """Calculates the reputation score for the npm project listing."""
        if not project_data or project_data.get(
            Keys.ERROR
        ):  # MODIFIED: Used Keys.ERROR
            logging.warning(
                "NPM project data is missing or contains an error, assigning zero score."
            )
            return 0.0

        package_name = project_data.get(
            Keys.PACKAGE_NAME, "Unknown Package"
        )  # MODIFIED
        logging.debug(f"Calculating NPM score for {package_name}...")

        # Extract values (with defaults for safety)
        downloads = project_data.get(Keys.DOWNLOADS_LAST_MONTH, 0)  # MODIFIED
        num_versions = project_data.get(Keys.NUM_VERSIONS, 0)  # MODIFIED
        days_updated = project_data.get(Keys.DAYS_SINCE_LAST_UPDATED)  # MODIFIED
        days_created = project_data.get(Keys.DAYS_SINCE_CREATED)  # MODIFIED
        license_val = project_data.get(Keys.LICENSE_INFO)  # MODIFIED
        num_maintainers = project_data.get(Keys.NUM_MAINTAINERS, 0)  # MODIFIED
        homepage_url = project_data.get(Keys.HOMEPAGE_URL)  # MODIFIED
        bug_tracker_url = project_data.get(Keys.BUG_TRACKER_URL)  # MODIFIED

        # Score components
        downloads_score = self._normalize_log(downloads or 0, MAX_LOG_NPM_DOWNLOADS)
        versions_score = self._normalize_log(num_versions or 0, MAX_LOG_NPM_VERSIONS)

        recency_score = self._score_npm_recency(days_updated)
        age_score = self._age_score(days_created)

        license_key_to_score = None
        if isinstance(license_val, str):
            license_key_to_score = license_val
        elif isinstance(license_val, dict):
            license_key_to_score = license_val.get(
                "type"
            )  # Common field for SPDX type in npm license objects

        license_score_val = self._score_license(license_key_to_score)

        maintainers_score = self._normalize_log(
            num_maintainers or 0, MAX_LOG_NPM_MAINTAINERS
        )

        bonus_score_component = 0.0
        if homepage_url:
            bonus_score_component += 0.5
        if bug_tracker_url:
            bonus_score_component += 0.5
        # bonus_score_component is now 0, 0.5, or 1.0

        # Weighted sum
        # Weights: Downloads (0.30), Versions (0.15), Recency (0.20), Age (0.10), License (0.10), Maintainers (0.10), Bonuses (0.05)
        # Sum of weights = 0.30 + 0.15 + 0.20 + 0.10 + 0.10 + 0.10 + 0.05 = 1.0
        score = (
            0.30 * downloads_score
            + 0.25 * versions_score
            + 0.15 * age_score
            + 0.10 * license_score_val
            + 0.20 * maintainers_score
        )

        logger.info(
            f"NPM Score Components for {package_name}: "
            f"Downloads: {downloads_score:.2f} (Raw: {downloads}), "
            f"Versions: {versions_score:.2f} (Raw: {num_versions}), "
            f"Recency: {recency_score:.2f} (Days: {days_updated}), "
            f"Age: {age_score:.2f} (Days: {days_created}), "
            f"License: {license_score_val:.2f} (Key: {license_key_to_score}), "
            f"Maintainers: {maintainers_score:.2f} (Raw: {num_maintainers}), "
            f"Bonuses: {bonus_score_component:.2f} (Homepage: {'Yes' if homepage_url else 'No'}, Bugs: {'Yes' if bug_tracker_url else 'No'})"
        )

        final_npm_score = (
            min(score, 1.0) * 100
        )  # Ensure score is capped at 1.0 before scaling to 0-100
        logger.info(
            f"Calculated NPM Score for {package_name}: {final_npm_score:.2f}/100"
        )
        return final_npm_score

    def _score_npm_recency(self, days_since_updated: Optional[int]) -> float:
        """Scores package recency based on days since last update."""
        if days_since_updated is None or days_since_updated < 0:
            logging.debug(
                "NPM recency: No valid 'days_since_updated' data, scoring 0.0."
            )
            return 0.0
        if days_since_updated <= 30:  # Updated within the last month
            return 1.0
        elif days_since_updated <= 90:  # Updated within the last 3 months
            return 0.8
        elif days_since_updated <= 180:  # Updated within the last 6 months
            return 0.5
        elif days_since_updated <= 365:  # Updated within the last year
            return 0.2
        else:  # Not updated for over a year
            logging.debug(
                f"NPM recency: Package not updated for {days_since_updated} days, scoring 0.0."
            )
            return 0.0

    def _age_score(self, days_since_created: Optional[int]) -> float:
        """Scores package age based on days since creation."""
        if days_since_created is None or days_since_created < 0:
            logging.debug("NPM age: No valid 'days_since_created' data, scoring 0.0.")
            return 0.0
        if days_since_created <= 10:
            return 0.0
        elif days_since_created <= 30:
            return 0.3
        elif days_since_created <= 90:
            return 0.6
        else:
            return 1.0

    def analyze(
        self, market_place: Optional[str], project_name: str
    ) -> Tuple[float, Dict[str, float]]:
        """
        Analyzes the collected project data to calculate a weighted reputation score.

        Returns:
            Tuple[float, Dict[str, float]]: A tuple containing the final reputation score (0-100)
                                             and a dictionary with the individual component scores.
        """
        try:
            project_data = self.get_project_data(
                market_place=market_place, project_name=project_name
            )
            owner_data = project_data.get(Keys.GITHUB_OWNER_METADATA, {})
            repo_data = project_data.get(Keys.GITHUB_REPO_METADATA, {})
            source_data = project_data.get(Keys.PROJECT_METADATA, {})

            owner_score = self._calculate_owner_score(owner_data)
            repo_score = self._calculate_repo_score(repo_data)

            source_score = 0.0  # Default source score
            if market_place == MarketPlaces.SMITHERY:
                source_score = self._calculate_smithery_score(source_data)
                final_score = max(owner_score, repo_score, source_score)
                component_scores = {
                    Keys.OWNER_SCORE: round(owner_score, 2),
                    Keys.REPO_SCORE: round(repo_score, 2),
                    Keys.SOURCE_SCORE: round(source_score, 2),
                }

            elif market_place == MarketPlaces.NPM:
                source_score = self._calculate_npm_score(source_data)
                project_score = (
                    repo_score * NPM_REPO_WEIGHT_IN_PACKAGE_SCORE
                    + source_score * NPM_REGISTRY_WEIGHT_IN_PACKAGE_SCORE
                )
                final_score = max(owner_score, project_score)

                component_scores = {
                    Keys.OWNER_SCORE: round(owner_score, 2),
                    Keys.PROJECT_SCORE: round(project_score, 2),
                }

            logger.info(
                f"Reputation analysis complete for {project_name}. Final Score: {final_score:.2f}"
            )
            logger.info(f"Component Scores: {component_scores}")

            return round(final_score, 2), component_scores

        except Exception as e:
            logging.error(
                f"Error during analysis for {project_name}: {e}", exc_info=True
            )
            # Return a default score or re-raise depending on desired behavior
            return 0.0, {
                Keys.OWNER_SCORE: 0.0,
                Keys.REPO_SCORE: 0.0,
                Keys.SMITHERY_SCORE: 0.0,
            }


# Example Usage (Optional - for testing or direct execution)
if __name__ == "__main__":
    # This part will only run when the script is executed directly
    # Replace with actual project details or use command-line arguments
    try:
        # Example: analyze 'cursor' project from 'smithery'
        analyzer = ProjectAnalyzer()
        test = analyzer.get_project_data(
            market_place="smithery",
            project_name="@smithery-ai/server-sequential-thinking",
        )
        print(test)
        final_score, component_scores = analyzer.analyze(
            market_place="smithery",
            project_name="@smithery-ai/server-sequential-thinking",
        )
        for component, score in component_scores.items():
            print(f"  - {component}: {score}")
        print("--------------------------------------------------")

    except ValueError as ve:
        print(f"Configuration Error: {ve}")
    except Exception as ex:
        print(f"An unexpected error occurred: {ex}")
