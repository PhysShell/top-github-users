"""Fixed-period public contribution ranking, using only Python's standard library."""
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import threading
from pathlib import Path
import time
import urllib.error
import urllib.request

FROM = '2025-09-17T03:11:00Z'
TO = '2026-09-17T03:11:00Z'
FIELDS = '''login location followers { totalCount }
contributionsCollection(from: $from, to: $to) {
  contributionCalendar { totalContributions }
  restrictedContributionsCount
}'''
REQUEST_LOCK = threading.Lock()
NEXT_REQUEST_AT = 0.0


def api(query, variables):
    global NEXT_REQUEST_AT
    request = urllib.request.Request('https://api.github.com/graphql',
        json.dumps({'query': query, 'variables': variables}).encode(),
        {'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
         'Content-Type': 'application/json', 'User-Agent': 'kazakhstan-ranking'})
    for attempt in range(5):
        with REQUEST_LOCK:
            time.sleep(max(0, NEXT_REQUEST_AT - time.monotonic()))
            NEXT_REQUEST_AT = time.monotonic() + 3
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.load(response)
            if result.get('errors'):
                message = json.dumps(result['errors'])
                if 'timeout' in message.lower() or 'something went wrong' in message.lower():
                    raise TimeoutError(message)
                raise RuntimeError(message)
            return result['data']
        except urllib.error.HTTPError as error:
            if error.code in (403, 429):
                body = error.read().decode('utf-8', errors='replace')
                if error.code == 403 and not any(term in body.lower() for term in ('rate limit', 'abuse', 'temporarily')):
                    raise RuntimeError(f'GitHub HTTP 403: {body}') from error
                delay = max(60 * (attempt + 1), int(error.headers.get('Retry-After', '0')))
                with REQUEST_LOCK:
                    NEXT_REQUEST_AT = max(NEXT_REQUEST_AT, time.monotonic() + delay)
                print(f'GitHub temporary request limit; pausing {delay}s', flush=True)
                if attempt == 4:
                    raise RuntimeError(f'GitHub request limit persists: {body}') from error
                continue
            if error.code not in (429, 500, 502, 503, 504) or attempt == 4:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 4:
                raise
        time.sleep(3 * (attempt + 1))


def main():
    country = json.loads(Path('config.json').read_text())['locations'][0]
    base = ' '.join('location:' + place.replace(' ', '_').lower()
                    for place in [country['country'], *country['cities']])
    query = '''query($q: String!, $cursor: String) {
      search(type: USER, query: $q, first: 100, after: $cursor) {
        userCount pageInfo { hasNextPage endCursor }
        nodes { ... on User { login location followers { totalCount } } }
      }
    }'''
    period = {'from': FROM, 'to': TO}
    users, partitions = {}, []

    def collect(low, high, created_start=None, created_end=None):
        q = f'{base} followers:{low}..{high} sort:followers-desc'
        if created_start is not None:
            q += f' created:{created_start.isoformat()}..{created_end.isoformat()}'
        cursor, first = None, True
        while True:
            data = api(query, {'q': q, 'cursor': cursor})['search']
            if first and data['userCount'] > 1000:
                if low != high:
                    middle = (low + high) // 2
                    collect(low, middle)
                    collect(middle + 1, high)
                else:
                    start = created_start or datetime.date(2008, 1, 1)
                    end = created_end or datetime.datetime.now(datetime.timezone.utc).date()
                    if start == end:
                        raise RuntimeError(f'Search limit exceeded at {low} followers on {start}')
                    middle = start + (end - start) // 2
                    collect(low, high, start, middle)
                    collect(low, high, middle + datetime.timedelta(days=1), end)
                return
            if first:
                partitions.append({'query': q, 'userCount': data['userCount']})
            first = False
            for user in data['nodes']:
                if user.get('login'):
                    users[user['login'].lower()] = user
            print(f'Fetched {len(users)} users', flush=True)
            if not data['pageInfo']['hasNextPage']:
                return
            cursor = data['pageInfo']['endCursor']
            time.sleep(1)

    maximum = api('''query($q: String!) {
      search(type: USER, query: $q, first: 1) {
        nodes { ... on User { followers { totalCount } } }
      }
    }''', {'q': base + ' sort:followers-desc'})['search']['nodes']
    if not maximum:
        raise RuntimeError('Empty country search')
    full_coverage = os.environ.get('FULL_COVERAGE', 'false').lower() == 'true'
    if full_coverage:
        collect(0, maximum[0]['followers']['totalCount'])
    else:
        cursor = None
        for page in range(10):
            q = base + ' sort:followers-desc'
            data = api(query, {'q': q, 'cursor': cursor})['search']
            if page == 0:
                partitions.append({'query': q, 'userCount': data['userCount'], 'resultLimit': 1000})
            for user in data['nodes']:
                if user.get('login'):
                    users[user['login'].lower()] = user
            print(f'Fetched {len(users)} users (upstream selection)', flush=True)
            if not data['pageInfo']['hasNextPage']:
                break
            cursor = data['pageInfo']['endCursor']
    found = 'physshell' in users
    logins = [user['login'] for user in users.values()]
    if not found:
        logins.append('PhysShell')
    users = {}

    def fetch_batch(batch):
        fields = '\n'.join(f'u{i}: user(login: {json.dumps(login)}) {{ {FIELDS} }}'
                           for i, login in enumerate(batch))
        try:
            data = api('query($from: DateTime!, $to: DateTime!) { ' + fields + ' }', period)
        except RuntimeError as error:
            if 'RESOURCE_LIMITS_EXCEEDED' not in str(error) or len(batch) == 1:
                raise
            middle = len(batch) // 2
            fetch_batch(batch[:middle])
            fetch_batch(batch[middle:])
            return
        for user in data.values():
            if user:
                users[user['login'].lower()] = user
        print(f'Contributions fetched: {len(users)}/{len(logins)}', flush=True)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(fetch_batch, logins[start:start + 20])
                   for start in range(0, len(logins), 20)]
        for future in as_completed(futures):
            future.result()
    target = users.get('physshell')
    if not target:
        raise RuntimeError('PhysShell missing')
    for user in users.values():
        c = user.pop('contributionsCollection')
        user['followers'] = user['followers']['totalCount']
        user['totalContributions'] = c['contributionCalendar']['totalContributions']
        user['restrictedContributionsCount'] = c['restrictedContributionsCount']
        user['publicContributions'] = user['totalContributions'] - user['restrictedContributionsCount']
    ranking = sorted(users.values(), key=lambda u: (-u['publicContributions'], -u['followers'], u['login'].lower()))
    rank = 1 + sum(u['publicContributions'] > target['publicContributions'] for u in ranking)
    metadata = {**period, 'generatedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'selectionMode': 'full-location-search' if full_coverage else 'upstream-top-1000-search-results',
                'targetFoundInLocationSearch': found, 'targetRank': rank,
                'searchPartitions': partitions, 'users': ranking}
    Path('cache').mkdir(exist_ok=True)
    Path('cache/kazakhstan-fixed-period.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + '\n')
    lines = ['# Kazakhstan public contributions — fixed period', '',
        f'Period: `{FROM}` → `{TO}`.', f'Generated: `{metadata["generatedAt"]}`.',
        f'PhysShell: **{target["publicContributions"]} contributions; rank #{rank}**.',
        f'Found by location search: **{found}**. Accounts fetched: **{len(ranking)}**.', '',
        f'Selection mode: `{metadata["selectionMode"]}`.', '',
        'Equal contribution counts share a rank. Search is partitioned by followers and account creation date to avoid the 1,000-result cap.',
        'Coverage includes GitHub location search results, not every developer in Kazakhstan.',
        'Profile locations and follower counts are current; contribution dates are fixed.', '',
        '| Rank | User | Public contributions | Followers |', '| --- | --- | --- | --- |']
    previous = None
    for position, user in enumerate(ranking, 1):
        if user['publicContributions'] != previous:
            current_rank = position
        previous = user['publicContributions']
        if previous > 0:
            lines.append(f'| {current_rank} | [{user["login"]}](https://github.com/{user["login"]}) | {previous} | {user["followers"]} |')
    Path('markdown/public_contributions').mkdir(parents=True, exist_ok=True)
    Path('markdown/public_contributions/kazakhstan.md').write_text('\n'.join(lines) + '\n')
    print(f'PhysShell: {target["publicContributions"]} contributions, #{rank}', flush=True)


if __name__ == '__main__':
    main()
