#!/usr/bin/env python3
"""Run from the existing publish-github job; no shell expansion or token logging."""
import json
import os
import sys
import time
import urllib.error
import urllib.request

url = 'http://host.docker.internal:8097/v1/mirror'
try:
    body = {key: int(os.environ[env]) for key, env in (
        ('project_id', 'CI_PROJECT_ID'), ('pipeline_id', 'CI_PIPELINE_ID'), ('job_id', 'CI_JOB_ID'))}
    token = os.environ['CI_JOB_TOKEN']
except (KeyError, ValueError):
    print('Mirror: required CI identity is unavailable', file=sys.stderr)
    raise SystemExit(1)
body['dry_run'] = os.environ.get('MIRROR_DRY_RUN') == '1'
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise urllib.error.URLError('redirect refused')


opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
for attempt in range(3):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST',
        headers={'Content-Type': 'application/json', 'JOB-TOKEN': token})
    try:
        with opener.open(request, timeout=600) as response:
            result = json.load(response)
        print('Mirror:', json.dumps(result, sort_keys=True))
        raise SystemExit(0)
    except urllib.error.HTTPError as exc:
        # Print only the fixed controller error code; never headers or request data.
        try:
            value = json.load(exc)
            reason = value.get('error', 'controller_rejected')
        except (ValueError, OSError):
            reason = 'controller_unavailable'
        if exc.code not in (502, 503, 504) or attempt == 2:
            print(f'Mirror rejected: HTTP {exc.code}, {reason}', file=sys.stderr)
            raise SystemExit(1)
    except (urllib.error.URLError, TimeoutError, OSError):
        if attempt == 2:
            print('Mirror controller unavailable', file=sys.stderr)
            raise SystemExit(1)
    time.sleep(2 ** attempt)
