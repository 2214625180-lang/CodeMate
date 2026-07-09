import type { GitHubIdentity, GitHubOAuthConfig } from "./adminSession";

type GitHubTokenResponse = {
  access_token?: string;
  error?: string;
  error_description?: string;
};

type GitHubUserResponse = {
  login: string;
  name: string | null;
  avatar_url: string | null;
};

type GitHubOrgResponse = {
  login: string;
};

type GitHubTeamResponse = {
  slug: string;
  organization?: {
    login?: string;
  };
};

const GITHUB_API_VERSION = "2022-11-28";

export function githubAuthorizeUrl(config: GitHubOAuthConfig, redirectUri: string, state: string) {
  const params = new URLSearchParams({
    client_id: config.clientId,
    redirect_uri: redirectUri,
    scope: "read:user user:email read:org",
    state,
    allow_signup: "false"
  });
  return `https://github.com/login/oauth/authorize?${params.toString()}`;
}

export async function exchangeGitHubCode(
  config: GitHubOAuthConfig,
  code: string,
  redirectUri: string
): Promise<string> {
  const response = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      client_id: config.clientId,
      client_secret: config.clientSecret,
      code,
      redirect_uri: redirectUri
    })
  });
  const payload = (await response.json()) as GitHubTokenResponse;
  if (!response.ok || !payload.access_token) {
    throw new Error(payload.error_description || payload.error || "Failed to exchange GitHub code");
  }
  return payload.access_token;
}

export async function fetchGitHubIdentity(accessToken: string): Promise<GitHubIdentity> {
  const [user, orgs, teams] = await Promise.all([
    githubGet<GitHubUserResponse>(accessToken, "https://api.github.com/user"),
    githubGetPaginated<GitHubOrgResponse>(accessToken, "https://api.github.com/user/orgs"),
    githubGetPaginated<GitHubTeamResponse>(accessToken, "https://api.github.com/user/teams")
  ]);

  return {
    login: user.login,
    name: user.name,
    avatarUrl: user.avatar_url,
    orgs: orgs.map((org) => org.login).filter(Boolean),
    teams: teams
      .map((team) =>
        team.organization?.login && team.slug ? `${team.organization.login}/${team.slug}` : ""
      )
      .filter(Boolean)
  };
}

async function githubGetPaginated<T>(accessToken: string, url: string): Promise<T[]> {
  const items: T[] = [];
  for (let page = 1; page <= 10; page += 1) {
    const pageUrl = new URL(url);
    pageUrl.searchParams.set("per_page", "100");
    pageUrl.searchParams.set("page", String(page));
    const pageItems = await githubGet<T[]>(accessToken, pageUrl.toString());
    items.push(...pageItems);
    if (pageItems.length < 100) {
      break;
    }
  }
  return items;
}

async function githubGet<T>(accessToken: string, url: string): Promise<T> {
  const response = await fetch(url, {
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${accessToken}`,
      "User-Agent": "CodeMate-Evaluation-Center",
      "X-GitHub-Api-Version": GITHUB_API_VERSION
    },
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`GitHub API request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}
