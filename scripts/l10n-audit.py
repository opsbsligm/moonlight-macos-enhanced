#!/usr/bin/env python3
"""Report localization keys that the UI can ask for but no layer can answer.

A key is satisfied when either the inline table in LanguageManager or the
matching .strings table has an entry, because localize() consults the table
first and the bundle second. Keys missing from both render as the raw key.

The scan of the sources is done here, in Python, on purpose. It used to be a
`grep -rhoE` whose pattern contained a (?: group: BSD grep on macOS accepted it
and the local run reported 162 keys, while the ubuntu audit runner's grep
produced nothing, its stderr was captured and thrown away, and the audit printed
"0 keys referenced in code" and then "localization coverage is complete on both
sides" -- a gate that checked nothing and looked green doing it. Two things keep
that from coming back: the scan does not depend on a host regex dialect, and
scan_health() refuses to let an empty scan be read as a clean tree.

Usage: l10n-audit.py [root]
Exit 0 only when every key the code asks for is answered in both languages and
the scan is demonstrably running. The self-test has no opt-out, because a gate
whose proof can be switched off is not a gate: the tests call functions in this
file and never invoke it again, so there is nothing to recurse.
"""
import io, os, re, sys

positional = [a for a in sys.argv[1:] if not a.startswith("--")]
root = positional[0] if positional else "."

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

# The optional @ is not decoration: NSLocalizedString and MLString are ObjC macros
# over the same lookup, and every one of their 153 call sites passes an @"..."
# literal. A pattern that only allowed a bare quote saw 197 of the 350 call sites
# and reported the other half as covered, which is how the log browser strings
# went untranslated for a whole release.
CALL_PATTERN = re.compile(r'(?:localize\(|MLString\(|NSLocalizedString\()'
                          r'\(?@?"([^"]{1,120})"?')
# The same three calls as plain text, for a count that needs no regex dialect.
CALL_TOKENS = ("localize(", "MLString(", "NSLocalizedString(")
SOURCE_SUFFIXES = (".swift", ".m")


def source_texts(scan_root):
    for directory, _, names in os.walk(os.path.join(scan_root, "Limelight")):
        for name in sorted(names):
            if name.endswith(SOURCE_SUFFIXES):
                path = os.path.join(directory, name)
                yield path, io.open(path, encoding="utf-8", errors="replace").read()


def keys_in_source(text):
    """The keys one source file asks the localization layers for."""
    return {match.group(1) for match in CALL_PATTERN.finditer(text) if match.group(1)}


def referenced_keys(scan_root):
    used = set()
    for _, text in source_texts(scan_root):
        used |= keys_in_source(text)
    return used


def call_token_count(scan_root):
    return sum(text.count(token)
               for _, text in source_texts(scan_root) for token in CALL_TOKENS)


def scan_health(keys_found, tokens_present):
    """Why the scan cannot be trusted, or None when it can.

    Two independent counts have to agree that there is something to find: the
    regex scan above, and a plain substring count of the call tokens that needs
    no regex at all. Call sites present but no keys found can only mean the scan
    did not run here, which is exactly the state that used to print a green tick.
    """
    if keys_found:
        return None
    if tokens_present:
        return ("%d localization call sites are in the tree but the scan found no "
                "key, so the scan is not running on this machine" % tokens_present)
    return "no localization call site is in the tree, so this scan checked nothing"


failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


FIXTURES = [
    ("localize call", 'Text(localize("settings.title"))', {"settings.title"}),
    ("localize with an extra paren", 'localize(("help.body"))', {"help.body"}),
    ("MLString call", 'Text(MLString("video.quality"))', {"video.quality"}),
    ("NSLocalizedString call",
     '[NSString stringWithFormat:NSLocalizedString(@"menu.reconnect", nil)]',
     {"menu.reconnect"}),
    ("MLString with an at-quoted key",
     'MLString(@"Mouse Mode On", @"Notification")', {"Mouse Mode On"}),
    ("a plain string is not a call", 'Text("not.a.call.site")', set()),
]

# keys found, call tokens, whether the scan has to be refused.
HEALTH_CASES = [
    (162, 439, False),
    (0, 439, True),
    (0, 0, True),
]


def self_test():
    for name, source, expected in FIXTURES:
        found = keys_in_source(source)
        check(found == expected, "scanner %s" % name if found == expected
              else "scanner %s found %s, expected %s" % (name, sorted(found), sorted(expected)))
    for keys_found, tokens, must_refuse in HEALTH_CASES:
        problem = scan_health(keys_found, tokens)
        refused = problem is not None
        label = "an empty scan with %d call sites present" % tokens if keys_found == 0 \
            else "a scan that found %d keys" % keys_found
        check(refused == must_refuse,
              "scan health %s" % ("refuses" if must_refuse else "accepts") + " " + label
              if refused == must_refuse else
              "scan health %s: %s" % ("missed" if must_refuse else "wrongly refused", label))


print("localization: %d english keys, %d chinese keys, %d keys referenced in code"
      % (len(en), len(zh), len(referenced_keys(root))))

used = referenced_keys(root)
health = scan_health(len(used), call_token_count(root))
check(health is None, "the scan sees the keys the code asks for"
      if health is None else "the localization scan is vacuous: " + health)
check(bool(en) and bool(zh), "both translation layers have entries to compare against")

missing_zh = sorted(k for k in used if k not in zh)
missing_en = sorted(k for k in used if k not in en)
for label, keys in (("chinese", missing_zh), ("english", missing_en)):
    for key in keys:
        print("::error file=Limelight/macOS/Helpers/LanguageManager.swift::"
              "localization key has no %s entry: %s" % (label, key))
check(not missing_zh and not missing_en,
      "localization coverage is complete on both sides"
      if not (missing_zh or missing_en) else
      "unanswered localization keys: chinese %d, english %d" % (len(missing_zh), len(missing_en)))

# The scan and its health rule are the whole value of this audit, so they are
# tested here rather than assumed: an audit that cannot tell a clean tree from a
# blind scanner is not a gate.
self_test()

print("%d localization failures" % len(failures))
sys.exit(1 if failures else 0)
