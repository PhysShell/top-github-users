# Kazakhstan public contributions for a fixed period

This fork recalculates Kazakhstan for **2025-09-17 03:11 UTC through 2026-09-17 03:11 UTC**.

- [Ranking](markdown/public_contributions/kazakhstan.md)
- [Raw results and search partitions](cache/kazakhstan-fixed-period.json)
- [Run the workflow](../../actions/workflows/action.yml) using **Run workflow**.

The workflow uses the repository secret `CUSTOM_TOKEN` for API reads, falling back to the built-in GitHub Actions token if the secret is absent. The built-in token is used for committing results. No token is stored in source files. It writes updated results to `main` and uploads a result artifact. Scheduled runs are disabled because the contribution period is fixed.

The script preserves the upstream Kazakhstan/city location query, partitions searches by followers and account creation dates to avoid the 1,000-result search cap, and calculates `totalContributions - restrictedContributionsCount` for every returned user. PhysShell is included explicitly if location search does not return it; this is recorded in the JSON. Equal contribution counts share the same rank.

Locations and follower counts reflect the time of collection, not historical profile settings. Search coverage depends on GitHub location search, and is not a census of all developers in Kazakhstan. A failed run does not publish partial results. Other country files inherited from upstream are not recalculated by this fork.

To run locally with Python 3.12 or later and an authenticated GitHub CLI:

```bash
export GH_TOKEN="$(gh auth token)"
python scripts/kazakhstan_ranking.py
unset GH_TOKEN
```

Period constants are in `scripts/kazakhstan_ranking.py`. Country and cities are in `config.json`.

Source project: [gayanvoice/top-github-users](https://github.com/gayanvoice/top-github-users), generator: [gayanvoice/top-github-users-action](https://github.com/gayanvoice/top-github-users-action). Upstream cache data is distributed under [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
