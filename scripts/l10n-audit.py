#!/usr/bin/env python3
"""Report localization keys that the UI can ask for but no layer can answer.

A key is satisfied when either the inline table in LanguageManager or the
matching .strings table has an entry, because localize() consults the table
first and the bundle second. Keys missing from both render as the raw key.
"""
import io, re, subprocess, sys, os

root = sys.argv[1] if len(sys.argv) > 1 else "."
lm_path = os.path.join(root, "Limelight/macOS/Helpers/LanguageManager.swift")
lm = io.open(lm_path, encoding="utf-8").read()

def inline_table(name):
    m = re.search(r"private let %s: \[String: String\] = \[(.*?)\n  \]" % name, lm, re.S)
    if not m:
        raise SystemExit("cannot locate inline table %r" % name)
    return set(re.findall(r'^\s*"((?:[^"\\]|\\.)+)"\s*:', m.group(1), re.M))

def strings_table(path):
    if not os.path.exists(path):
        return set()
    return set(re.findall(r'^"((?:[^"\\]|\\.)+)"\s*=',
                          io.open(path, encoding="utf-8").read(), re.M))

en = inline_table("en") | strings_table(
    os.path.join(root, "Limelight/macOS/en.lproj/Localizable.strings"))
zh = inline_table("zhHans") | strings_table(
    os.path.join(root, "Limelight/macOS/zh-Hans.lproj/Localizable.strings"))

pattern = (r'(?:localize\(|MLString\(|NSLocalizedString\()'
           r'\(?"([^"]{1,120})"?')
out = subprocess.run(
    ["grep", "-rhoE", pattern, "--include=*.swift", "--include=*.m",
     os.path.join(root, "Limelight")],
    capture_output=True, text=True).stdout
used = {m.group(1) for m in re.finditer(pattern, out) if m.group(1)}

missing_zh = sorted(k for k in used if k not in zh)
missing_en = sorted(k for k in used if k not in en)

print("localization: %d english keys, %d chinese keys, %d keys referenced in code"
      % (len(en), len(zh), len(used)))
for label, keys in (("chinese", missing_zh), ("english", missing_en)):
    for key in keys:
        print("::error file=Limelight/macOS/Helpers/LanguageManager.swift::"
              "localization key has no %s entry: %s" % (label, key))

if missing_zh or missing_en:
    sys.exit(1)
print("localization coverage is complete on both sides")
