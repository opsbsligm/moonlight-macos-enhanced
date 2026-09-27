#!/usr/bin/env python3
"""Repeatable local gate: run the ordered key/mouse regression list, one log per
script plus a JSON summary, so an install decision can cite one artifact pair."""
from pathlib import Path
import json, subprocess, sys, time

SCRIPTS = [
 'input-boundary-tests','input-bind-retry-tests','edge-sensor-summon-tests','input-concurrency-tests',
 'mouse-button-state-tests','mouse-first-click-tests','corehid-lifecycle-tests','input-context-lifecycle-tests',
 'input-edge-queue-tests','controller-mouse-ownership-tests','keyboard-source-quirk-tests','keyboard-concurrency-tests',
 'held-key-identity-tests','held-modifier-keyboard-pair-tests','key-state-heal-tests','modifier-only-release-collision-tests',
 'key-order-exhaustive-tests','translation-rule-consumption-tests','gameplay-modifier-tests','controller-key-navigation-tests',
 'space-transition-held-key-tests','keyboard-modifier-mapping-tests','keyboard-shortcut-modifier-tests','command-to-control-tests',
 'sas-preset-tests','gamepad-menu-gesture-tests','controller-mouse-emulation-tests','discrete-scroll-click-tests',
 'scroll-notch-consumption-tests','relative-pointer-gain-tests','system-hotkey-capture-tests','shortcut-menu-key-tests',
 'pointer-entry-takeover-tests','input-wire-trace-tests','key-code-read-site-audit',
 'input-boundary-tests','discrete-scroll-click-tests','mouse-button-state-tests','corehid-lifecycle-tests',
 'input-context-lifecycle-tests','controller-mouse-emulation-tests','input-wire-trace-tests','key-code-read-site-audit',
 'system-hotkey-capture-tests','scroll-notch-consumption-tests',
]

def main():
    prefix = 'input-regression'
    if '--prefix' in sys.argv:
        prefix = sys.argv[sys.argv.index('--prefix') + 1]
    root = Path(__file__).resolve().parents[1]
    out = root / 'build-input-review'
    out.mkdir(exist_ok=True)
    results, failures = [], 0
    for i, name in enumerate(SCRIPTS):
        script = root / 'scripts' / (name + '.py')
        start = time.time()
        proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, cwd=root)
        seconds = round(time.time() - start, 2)
        log = out / f'{prefix}-{i + 1:02d}-{name}.log'
        log.write_text(f'$ python3 scripts/{name}.py\n[exit {proc.returncode}]\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}')
        results.append({'script': name, 'index': i + 1, 'exit': proc.returncode, 'seconds': seconds, 'log': log.name})
        if proc.returncode != 0:
            failures += 1
            print(f'FAIL {name} (exit {proc.returncode}) -> {log.name}')
        else:
            print(f'ok   {name} {seconds}s')
    summary = {'prefix': prefix, 'passed': len(SCRIPTS) - failures, 'failed': failures, 'results': results}
    (out / f'{prefix}-regression.json').write_text(json.dumps(summary, indent=2))
    print(f"{summary['passed']} passed, {failures} failed; summary {out.name}/{prefix}-regression.json")
    return 1 if failures else 0

if __name__ == '__main__':
    sys.exit(main())
