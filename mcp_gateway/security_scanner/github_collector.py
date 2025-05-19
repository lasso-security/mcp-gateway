import requests
from mcp_gateway.security_scanner.config import Keys

class GithubFetcher:
    def __init__(self, url: str):
        self.url = url
        splited_url = self.url.split("https://github.com/")[-1].split("/")
        self.repository_name = splited_url[1]
        self.owner = splited_url[0]

    def get_repository_metadata(self):
        try:
            repository_api_url = f"https://api.github.com/repos/{self.owner}/{self.repository_name}"
            response = requests.get(repository_api_url)
            repo_data = response.json()
            stars = repo_data.get(Keys.STARGAZERS_COUNT, 0)
            forks = repo_data.get(Keys.FORKS, 0)
            updated_at = repo_data.get(Keys.UPDATED_AT)
            created_at = repo_data.get(Keys.CREATED_AT)
            
            license_info = repo_data.get(Keys.LICENSE, {})
            github_license_key = None
            if license_info and isinstance(license_info, dict):
                license_key = license_info.get(Keys.LICENSE)
                if license_key and license_key != 'other':
                    github_license_key = license_key
                else:
                    github_license_key = license_info.get(Keys.NAME)
            return {
                Keys.STARS: stars,
                Keys.FORKS: forks,
                Keys.LICENSE: github_license_key,
                Keys.UPDATED_AT: updated_at,
                Keys.CREATED_AT: created_at,
            }
        except Exception as e:
            print(f"Error fetching repository metadata: {e}")
            return None

    def get_owner_metadata(self):
        organization_api_url = f"https://api.github.com/orgs/{self.owner}"
        owner_response = requests.get(organization_api_url)
        if owner_response.status_code != 200:
            owner_api_url = f"https://api.github.com/users/{self.owner}"
            owner_response = requests.get(owner_api_url)
        
        owner_data = owner_response.json()
        owner_type = owner_data.get(Keys.TYPE, "Unknown")
        followers = owner_data.get(Keys.FOLLOWERS, 0)
        public_repos_number = owner_data.get(Keys.PUBLIC_REPOS, 0)
        verified = owner_data.get(Keys.IS_VERIFIED, False)
        blog = owner_data.get(Keys.BLOG, None)
        email = owner_data.get(Keys.EMAIL, None)
        location = owner_data.get(Keys.LOCATION, None)
        created_at = owner_data.get(Keys.CREATED_AT, None)
        twitter_username = owner_data.get(Keys.TWITTER_USERNAME, None)
        return {
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

    def get_repository_data(self):
        repo_metadata = self.get_repository_metadata()
        owner_metadata = self.get_owner_metadata()
        return [repo_metadata, owner_metadata]

if __name__ == "__main__":
    # fetcher = GithubFetcher("https://github.com/barlanyado/mcp-server-test")
    fetcher = GithubFetcher("https://github.com/lasso-security/litellm")
    print(fetcher.get_repository_data())

