import pytest
import math
from typing import Dict, Any, Tuple
from datetime import datetime, timezone

from mcp_gateway.security_scanner.project_analyzer import ProjectAnalyzer, NPM_REPO_WEIGHT_IN_PACKAGE_SCORE, NPM_REGISTRY_WEIGHT_IN_PACKAGE_SCORE
from mcp_gateway.security_scanner.config import Keys, MarketPlaces

# Fixed "now" for consistent age calculations in tests
MOCK_NOW = datetime(2025, 5, 20, 0, 0, 0, tzinfo=timezone.utc)

class TestProjectAnalyzerGetProjectData:
    """
    Tests for the ProjectAnalyzer.get_project_data method.
    Focuses on the structure and types of the returned data.
    Some tests will make live API calls.
    """

    def _assert_dict_types(self, data_dict: Dict[str, Any], expected_types: Dict[str, Any], allow_missing_keys: bool = False) -> None:
        """Helper to assert types of values in a dictionary."""
        if not data_dict and not expected_types: # Both empty is fine
            return
        assert isinstance(data_dict, dict), f"Expected a dictionary, got {type(data_dict)}"
        
        for key, expected_type in expected_types.items():
            if key not in data_dict:
                if allow_missing_keys:
                    # Key is optional and not present, this is acceptable by type hint (e.g. Optional[str])
                    # We can infer this if expected_type is a tuple containing type(None)
                    assert isinstance(expected_type, tuple) and type(None) in expected_type, \
                        f"Key '{key}' is missing, but type hint {expected_type} does not suggest it is optional or it wasn't allowed to be missing."
                    continue
                else:
                    assert False, f"Key '{key}' not found in dictionary and missing keys are not allowed by this assertion."
            
            # For optional keys that might be None, expected_type can be a tuple including type(None)
            current_value = data_dict[key]
            if isinstance(expected_type, tuple):
                # This checks if current_value is an instance of ANY of the types in the tuple
                # or if current_value is None AND type(None) is in the expected_type tuple
                is_type_match = any(isinstance(current_value, t) for t in expected_type if t is not type(None))
                is_none_allowed_and_present = (type(None) in expected_type and current_value is None)
                
                assert is_type_match or is_none_allowed_and_present, \
                    f"Key '{key}' has value '{current_value}' of type {type(current_value)}, expected one of types {expected_type}."
            else:
                assert isinstance(current_value, expected_type), \
                    f"Key '{key}' has value '{current_value}' of type {type(current_value)}, expected {expected_type}."

    # Removed @patch decorators for SmitheryFetcher and GithubFetcher to make live calls
    def test_get_project_data_smithery_live_types(self) -> None:
        """
        Tests get_project_data for Smithery with live API calls, focusing on data types.
        Requires the project @smithery-ai/server-sequential-thinking to exist on Smithery.
        """
        analyzer = ProjectAnalyzer()
        project_name = "@smithery-ai/server-sequential-thinking" # Actual project on Smithery
        market_place = MarketPlaces.SMITHERY

        # This will make actual network calls
        result = analyzer.get_project_data(market_place=market_place, project_name=project_name)

        assert Keys.PROJECT_METADATA in result
        assert Keys.GITHUB_REPO_METADATA in result
        assert Keys.GITHUB_OWNER_METADATA in result

        # Define expected types for common/stable fields from live Smithery & GitHub APIs
        # These might need adjustment based on actual live data from the specific project
        expected_project_meta_types = {
            Keys.GITHUB_LINK: (str, type(None)),
            Keys.VERIFIED: (bool, type(None)),
            Keys.LICENSE: (str, type(None)),
            Keys.MONTHLY_TOOL_USAGE: (int, type(None)),
            Keys.RUNNING_LOCAL: (str, type(None)),
            Keys.PUBLISHED_AT: (str, type(None)),
        }
        
        # Common GitHub repo fields
        expected_repo_meta_types = {
            Keys.STARS: (int, type(None)),
            Keys.FORKS: (int, type(None)),
            Keys.LICENSE: (str, type(None)),
            Keys.UPDATED_AT: (str, type(None)),
            Keys.CREATED_AT: (str, type(None)),
        }
        
        # Common GitHub owner fields
        expected_owner_meta_types = {
            Keys.FOLLOWERS: (int, type(None)),
            Keys.VERIFIED: (bool, type(None)),
            Keys.PUBLIC_REPOS_NUMBER: (int, type(None)),
            Keys.OWNER_TYPE: (str, type(None)),
            Keys.BLOG: (str, type(None)),
            Keys.EMAIL: (str, type(None)),
            Keys.LOCATION: (str, type(None)),
            Keys.CREATED_AT: (str, type(None)),
            Keys.TWITTER_USERNAME: (str, type(None)),
        }

        self._assert_dict_types(result[Keys.PROJECT_METADATA], expected_project_meta_types, allow_missing_keys=True)
        # For GitHub data, it might be empty if the link was bad or no data found, so allow empty dicts
        if result[Keys.GITHUB_REPO_METADATA]:
            self._assert_dict_types(result[Keys.GITHUB_REPO_METADATA], expected_repo_meta_types, allow_missing_keys=True)
        if result[Keys.GITHUB_OWNER_METADATA]:
            self._assert_dict_types(result[Keys.GITHUB_OWNER_METADATA], expected_owner_meta_types, allow_missing_keys=True)

    # Removed @patch decorators for NPMCollector and GithubFetcher to make live calls
    def test_get_project_data_npm_live_types(self) -> None:
        """
        Tests get_project_data for NPM with live API calls, focusing on data types.
        Requires the project @modelcontextprotocol/sdk to exist on NPM.
        """
        analyzer = ProjectAnalyzer()
        project_name = "@modelcontextprotocol/sdk" # Actual project on NPM
        market_place = MarketPlaces.NPM

        # This will make actual network calls
        result = analyzer.get_project_data(market_place=market_place, project_name=project_name)

        assert Keys.PROJECT_METADATA in result
        assert Keys.GITHUB_REPO_METADATA in result
        assert Keys.GITHUB_OWNER_METADATA in result

        # Define expected types for common/stable fields from live NPM & GitHub APIs
        expected_project_meta_types = {
            Keys.PACKAGE_NAME: str,
            Keys.GITHUB_LINK: (str, type(None)),
            Keys.DOWNLOADS_LAST_MONTH: (int, type(None)),
            Keys.DESCRIPTION: (str, type(None)),
            Keys.NUM_VERSIONS: (int, type(None)),
            Keys.DAYS_SINCE_LAST_UPDATED: (int, float, type(None)), # can be int or float if direct datetime used
            Keys.DAYS_SINCE_CREATED: (int, float, type(None)),
            Keys.LICENSE_INFO: (dict, str, type(None)), 
            Keys.NUM_MAINTAINERS: (int, type(None)),
            Keys.MAINTAINERS_NAMES: (list, type(None)),
            Keys.HOMEPAGE_URL: (str, type(None)),
            Keys.BUG_TRACKER_URL: (str, type(None)),
            Keys.KEYWORDS: (list, type(None)),
            "market_place": str
        }
        # Reuse GitHub expected types from Smithery test or define separately if structure varies
        expected_repo_meta_types = {
            Keys.STARS: (int, type(None)), Keys.FORKS: (int, type(None)),
            Keys.LICENSE: (dict, str, type(None)), Keys.UPDATED_AT: (str, type(None)),
            Keys.CREATED_AT: (str, type(None)), Keys.DESCRIPTION: (str, type(None)),
        }
        expected_owner_meta_types = {
            Keys.LOGIN: (str, type(None)), Keys.OWNER_TYPE: (str, type(None)),
            Keys.FOLLOWERS: (int, type(None)), Keys.CREATED_AT: (str, type(None)),
        }

        self._assert_dict_types(result[Keys.PROJECT_METADATA], expected_project_meta_types, allow_missing_keys=True)
        if result[Keys.GITHUB_REPO_METADATA]:
            self._assert_dict_types(result[Keys.GITHUB_REPO_METADATA], expected_repo_meta_types, allow_missing_keys=True)
        if result[Keys.GITHUB_OWNER_METADATA]:
            self._assert_dict_types(result[Keys.GITHUB_OWNER_METADATA], expected_owner_meta_types, allow_missing_keys=True)


    def test_get_project_data_unsupported_marketplace(self) -> None:
        """
        Tests get_project_data with an unsupported marketplace.
        It should raise a ValueError.
        """
        analyzer = ProjectAnalyzer()
        project_name = "any-project"
        market_place = "unknown_marketplace"

        with pytest.raises(ValueError, match=f"Market place {market_place} not supported"):
            analyzer.get_project_data(market_place=market_place, project_name=project_name)


def test_score_npm_project() -> None:
    """
    Tests the analyze method for an NPM project with user-provided-like data.
    Verifies final_score and component_scores.
    Owner score: ~100.0
    Repo score: ~79.65 (stars 1.0, forks 0.8217, license 0.5, age 1.0)
    NPM score: ~76.02 (downloads 1.0, versions 1.0, age 1.0, license 0.0, maintainers ~0.301)
    Project score (0.6*Repo + 0.4*NPM): ~78.20
    Final score: max(Owner, Project) = 100.0
    """
    npm_mock_data =  {
        Keys.PACKAGE_NAME: '@smithery/cli',
        Keys.DOWNLOADS_LAST_MONTH: 392944,
        Keys.NUM_VERSIONS: 122,
        Keys.DAYS_SINCE_LAST_UPDATED: 0,
        Keys.DAYS_SINCE_CREATED: 159, # npm_age_score 1.0
        Keys.LICENSE_INFO: None, # license_score 0.0
        Keys.NUM_MAINTAINERS: 1, # maintainers_score log10(2) ~0.301
        Keys.HOMEPAGE_URL: 'https://smithery.ai/',
        Keys.BUG_TRACKER_URL: 'https://github.com/smithery-ai/cli/issues',
    }
    
    repo_mock_data = {
        Keys.STARS: 283,
        Keys.FORKS: 43,
        Keys.LICENSE: 'GNU Affero General Public License v3.0', # scores 0.5
        Keys.CREATED_AT: '2024-12-22T04:43:16Z', # repo_age_score 1.0 with MOCK_NOW (149 days)
    }
    
    owner_mock_data = {
        Keys.FOLLOWERS: 848,
        Keys.VERIFIED: True,
        Keys.PUBLIC_REPOS_NUMBER: 845,
        Keys.OWNER_TYPE: Keys.ORGANIZATION_OWNER_TYPE,
        Keys.BLOG: 'https://smithery.ai/',
        Keys.CREATED_AT: '2024-12-03T11:50:24Z', # owner_age_score ~0.1534 with MOCK_NOW
        Keys.TWITTER_USERNAME: 'smitherydotai'
    }
    
    mock_project_data_val = {
        Keys.PROJECT_METADATA: npm_mock_data,
        Keys.GITHUB_REPO_METADATA: repo_mock_data,
        Keys.GITHUB_OWNER_METADATA: owner_mock_data,
    }
    
    expected_owner_score = 100.0
    analyzer = ProjectAnalyzer()
    owner_score = analyzer._calculate_owner_score(owner_mock_data)
    assert owner_score == expected_owner_score

    expected_repo_score = 79.65
    repo_score = analyzer._calculate_repo_score(repo_mock_data)
    assert repo_score == pytest.approx(expected_repo_score, abs=1e-2)

    expected_npm_score = 76.02
    npm_score = analyzer._calculate_npm_score(npm_mock_data)
    assert npm_score == pytest.approx(expected_npm_score, abs=1e-2)

    expected_project_score = 78.20
    project_score = repo_score * NPM_REPO_WEIGHT_IN_PACKAGE_SCORE + npm_score * NPM_REGISTRY_WEIGHT_IN_PACKAGE_SCORE
    assert project_score == pytest.approx(expected_project_score, abs=1e-2)

    expected_final_score = 100.0
    final_score = max(owner_score, project_score)
    assert final_score == pytest.approx(expected_final_score, abs=1e-2)


def test_score_smithery_project() -> None:
    
    smithery_mock_data = {
        'github_link': 'https://github.com/smithery-ai/reference-servers/tree/main/src/sequentialthinking',
        'verified': False,
        'license': 'MIT',
        'monthly_tool_usage': 147050,
        'running_local': 'No',
        'published_at': '12/13/2024',
        'market_place': 'smithery'
    }

    expected_smithery_score = 51.0
    analyzer = ProjectAnalyzer()
    smithery_score = analyzer._calculate_smithery_score(smithery_mock_data)
    assert smithery_score == pytest.approx(expected_smithery_score, abs=1e-2)
    
    repo_mock_data = {
        'stars': 306, 
        'forks': 47, 
        'license': 'MIT License', 
        'updated_at': '2025-05-19T11:19:54Z', 
        'created_at': '2025-01-18T08:28:30Z'
    }
    
    expected_repo_score = 80.22
    repo_score = analyzer._calculate_repo_score(repo_mock_data)
    assert repo_score == pytest.approx(expected_repo_score, abs=1e-2)
    
    owner_mock_data = {'followers': 848, 
            'verified': True, 
            'public_repos_number': 845, 
            'owner_type': 'Organization', 
            'blog': 'https://smithery.ai/', 
            'email': 'contact@smithery.ai', 
            'location': 'United States of America', 
            'created_at': '2024-12-03T11:50:24Z', 
            'twitter_username': 'smitherydotai'}
    
    expected_owner_score = 100.0
    owner_score = analyzer._calculate_owner_score(owner_mock_data)
    assert owner_score == pytest.approx(expected_owner_score, abs=1e-2)
    
    expected_final_score = 100.0
    final_score = max(owner_score, repo_score, smithery_score)
    assert final_score == pytest.approx(expected_final_score, abs=1e-2)
