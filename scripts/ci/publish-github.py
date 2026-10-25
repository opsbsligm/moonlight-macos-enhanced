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
# Backoff schedule: 5s, 15s, 30s, 60s, 120s (total ~230s).
# The 3-attempt/7s-total schedule from the original version could not survive
# a mirror-controller restart (observed 8-min outage, pipeline #510).
_BACKOFF = [5, 15, 30, 60, 120]
for attempt, delay in enumerate(_BACKOFF):
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
        if exc.code not in (502, 503, 504) or attempt == len(_BACKOFF) - 1:
            print(f'Mirror rejected: HTTP {exc.code}, {reason}', file=sys.stderr)
            raise SystemExit(1)
    except (urllib.error.URLError, TimeoutError, OSError):
        if attempt == len(_BACKOFF) - 1:
            print('Mirror controller unavailable after '
                  + str(len(_BACKOFF)) + ' attempts', file=sys.stderr)
            raise SystemExit(1)
    time.sleep(delay)
