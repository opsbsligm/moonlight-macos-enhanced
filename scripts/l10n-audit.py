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

KEY_LINE = re.compile(r'^"((?:[^"\\]|\\.)+)"\s*=', re.M)


def strings_key_list(path):
    """Every key a .strings table declares, in file order, repeats included."""
    if not os.path.exists(path):
        return []
    return KEY_LINE.findall(io.open(path, encoding="utf-8").read())


def strings_table(path):
    return set(strings_key_list(path))


def duplicate_keys_in_text(text):
    """Repeated keys in the text of a .strings table, parse included."""
    return duplicate_keys(KEY_LINE.findall(text))


def duplicate_keys(names):
    """Keys a table declares more than once, paired with how often."""
    seen = {}
    for name in names:
        seen[name] = seen.get(name, 0) + 1
    return sorted((name, count) for name, count in seen.items() if count > 1)


def table_symmetry(en_keys, zh_keys):
    """Keys one language table declares and the other does not.

    A key that exists on one side only is either a dead entry or a hole the
    coverage check below papers over, because the inline Swift table can answer
    for it. Either way the two tables have drifted, and the dedup pass that drops
    repeated keys is exactly the edit that removes one side and keeps the other, so
    the drift is named here instead of being left to show up in the UI.
    """
    only_en = sorted(set(en_keys) - set(zh_keys))
    only_zh = sorted(set(zh_keys) - set(en_keys))
    return only_en, only_zh


EN_TABLE = "Limelight/macOS/en.lproj/Localizable.strings"
ZH_TABLE = "Limelight/macOS/zh-Hans.lproj/Localizable.strings"

# The lists are read once and reused: the set is what answers a key, the list is
# what shows a key being declared twice or on one side only.
raw_en = strings_key_list(os.path.join(root, EN_TABLE))
raw_zh = strings_key_list(os.path.join(root, ZH_TABLE))

en = inline_table("en") | set(raw_en)
zh = inline_table("zhHans") | set(raw_zh)

# The optional @ is not decoration: NSLocalizedString and MLString are ObjC macros
# over the same lookup, and every one of their 153 call sites passes an @"..."
# literal. A pattern that only allowed a bare quote saw 197 of the 350 call sites
# and reported the other half as covered, which is how the log browser strings
# went untranslated for a whole release.
# The key body is read one character or one escape pair at a time, and there is
# deliberately no length cap on it. The pattern used to stop at [^"]{1,120}, which
# silently shortened every longer key to its first 120 characters and looked that
# fragment up in the tables: three alert strings of 121, 140 and 161 characters were
# reported as absent, and the cap itself was the blind spot -- a key too long to be
# read could never be reported as unread, only as missing. A newline is excluded
# because a source literal spells one as the two characters backslash-n, so a call
# whose closing quote has gone missing fails here instead of swallowing the rest of
# the file. The table readers below already allowed escape pairs; this makes the
# call site read keys the same way, so a key with an escaped quote stops being a
# pair of half keys.
CALL_PATTERN = re.compile(r'(?:localize\(|MLString\(|NSLocalizedString\()'
                          r'\(?@?"((?:[^"\\\n]|\\.)+)')
# The same three calls as plain text, for a count that needs no regex dialect.
# A log row is level, category and sentence, and the row is assembled in one helper so
# the shape is written down once. That also moves the two translated arguments out of a
# call the scanner knows, which is the exact way this audit used to report complete
# coverage over strings nobody could see: the first version of the helper took an
# `NSString *category` and localized it inside, so all twenty of its call sites looked
# like an ordinary method call and none of their keys were checked. A row is read here
# for its second and third arguments, and the level is left out because it is an ASCII
# severity tag rather than something a table translates.
# Written as a scan over arguments rather than one rigid pattern, because the sentence
# of a row is often assembled by stringWithFormat and a pattern that insists the third
# argument start with a quote sees no call at all there -- which is how the first
# version of this rule quietly checked fourteen of the twenty rows and reported the
# other six as needing nothing. Only an argument that is itself a literal is taken: a
# nested expression is left to the call scanner, which reads what is inside it without
# mistaking a fallback such as @"unknown" for UI text. The level is the first argument
# and is dropped, because it is an ASCII severity tag rather than a table entry.
STRING_LITERAL = re.compile(r'@?"((?:[^"\\\\\n]|\\\\.)+)"')


def top_level_arguments(text, start):
    """The arguments of one call, given the index just past its opening paren."""
    arguments, depth, current, index = [], 1, "", start
    while index < len(text) and depth:
        char = text[index]
        if char == '"':
            end_of_string = index + 1
            while end_of_string < len(text) and text[end_of_string] != '"':
                end_of_string += 2 if text[end_of_string] == "\\" else 1
            current += text[index:min(end_of_string + 1, len(text))]
            index = end_of_string + 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                break
        elif char == "," and depth == 1:
            arguments.append(current)
            current = ""
            index += 1
            continue
        current += char
        index += 1
    arguments.append(current)
    return arguments


def log_row_keys(text):
    """Every literal a log row hands a table, the severity tag excepted."""
    found = set()
    for match in re.finditer(r"\bMLLogRow\s*\(", text):
        arguments = top_level_arguments(text, match.end())
        for argument in arguments[1:]:
            literal = argument.strip().lstrip("@")
            if literal.startswith('"'):
                found.update(STRING_LITERAL.findall(literal))
    return found


def bad_mlstring_arity(text):
    """MLString invocations that are not the two-argument macro the header defines.

    Localization.h defines one macro with two parameters, the second accepted so a
    call site reads like NSLocalizedString. The preprocessor is not forgiving about
    that: a call with one argument is not a translated string with the comment left
    out, it is an error, and the target does not build. Five of those were written
    into the log-row work of this round and nothing here noticed, because CALL_PATTERN
    happily read the first literal of a one-argument call and reported the key as
    covered. A gate that reports coverage over text that cannot compile is reporting
    the shape of its own regex, not the state of the tree.
    """
    bad = []
    for match in re.finditer(r"\bMLString\s*\(", text):
        if text[:match.start()].rstrip().endswith("#define"):
            continue  # the definition itself, whose parameters are not arguments
        arguments = top_level_arguments(text, match.end())
        if len(arguments) != 2:
            bad.append("%d arguments at line %d"
                       % (len(arguments), text.count("\n", 0, match.start()) + 1))
    return bad


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
    return {match.group(1) for match in CALL_PATTERN.finditer(text) if match.group(1)} \
        | log_row_keys(text)


def unreadable_rows(text):
    """Log rows whose category or sentence the scan cannot read.

    A row assembled from a variable is correct code and a hole in this gate: the key
    exists only at run time, so no table can be asked whether it answers, and the row
    is counted as covered by the call sites that are literals. That is the same hole
    every other rule here was written against, so the shape is refused rather than
    tolerated.
    """
    unreadable = []
    for match in re.finditer(r"\bMLLogRow\s*\(", text):
        if text[:match.start()].rstrip().endswith("*"):
            continue  # the definition, whose parameters are variables by nature
        arguments = top_level_arguments(text, match.end())
        if len(arguments) < 3:
            unreadable.append("a row with %d arguments" % len(arguments))
            continue
        for argument in arguments[1:3]:
            stripped = argument.strip()
            if stripped.lstrip("@").startswith('"'):
                continue
            # A sentence assembled inline is fine as long as its own key sits in a call
            # the scan reads; what is refused is a key that exists only in a value.
            if any(token in stripped for token in CALL_TOKENS) and STRING_LITERAL.search(stripped):
                continue
            unreadable.append(stripped[:48] or "(nothing)")
    return unreadable


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

# Two shapes the capped pattern could not see. The long key is one the cap
# truncated, so it used to be reported as a missing translation rather than as a
# key the scanner could not read; the escaped quote used to end the match early and
# produce two half keys, neither of which any table can ever answer for.
LONG_KEY = "Diagnostics." + "detail " * 24
FIXTURES += [
    ("a key longer than the cap it used to carry",
     'MLString(@"%s", nil)' % LONG_KEY, {LONG_KEY}),
    ("a key carrying an escaped quote",
     r'MLString(@"Say \"hi\" to the host", nil)', {r'Say \"hi\" to the host'}),
]

# A log row keeps its own shape: the level is not translatable and must not be asked
# of a table, while the category and the sentence are, even though neither sits in a
# call the scanner was written for.
LOG_ROW_CASES = [
    ("a row built by the helper",
     'MLLogRow(@"INFO", @"Discovery", @"Scanning for hosts")',
     {"Discovery", "Scanning for hosts"}),
    ("a row whose sentence carries a placeholder",
     'MLLogRow(@"WARN", @"Network", [NSString stringWithFormat:MLString(@"NSURLError %@"), code])',
     {"Network", "NSURLError %@"}),
    ("a row whose category is a variable, which no scan can check",
     'MLLogRow(@"WARN", category, message)', set()),
]

ROW_SHAPES = [
    ("a row naming both halves as literals",
     'x = MLLogRow(@"INFO", @"Discovery", @"Scanning for hosts");', []),
    ("a row whose sentence is assembled inline",
     'x = MLLogRow(@"WARN", @"Network", [NSString stringWithFormat:MLString(@"NSURLError %@"), code]);',
     []),
    ("a row whose category arrives as a variable",
     'x = MLLogRow(@"WARN", category, @"Scanning for hosts");', ["category"]),
    ("a row whose sentence is a variable holding a translation",
     'x = MLLogRow(@"WARN", @"Network", sentence);', ["sentence"]),
    ("the definition itself, which is not a call",
     'static NSString *MLLogRow(NSString *level, NSString *category, NSString *message) {',
     []),
    ("a row missing its sentence",
     'x = MLLogRow(@"WARN", @"Network");', ["a row with 2 arguments"]),
]

# MLString is a two-parameter macro, so the count of arguments is part of the
# contract, not a style choice. A definition line is not a call.
ARITY_CASES = [
    ("a call with its key and its comment",
     'x = MLString(@"Scanning for hosts", nil);', []),
    ("a call with a comma inside the key",
     'x = MLString(@"Request failed %@, falling back automatically", nil);', []),
    ("a call with its comment left out",
     'x = MLString(@"Scanning for hosts");', ["1 arguments at line 1"]),
    ("a call with an argument too many",
     'x = MLString(@"Scanning for hosts", nil, @"extra");', ["3 arguments at line 1"]),
    ("the definition itself, which is not a call",
     '#define MLString(key, comment) [[LanguageManager shared] localize:key]', []),
]

# A repeated key is not a duplicate translation: the plist parser keeps the last
# one, so the entry above it is dead text that every reader of the file believes is
# live. Seven zh keys were silently translated twice this way, with the second
# answer winning, until a reader picked the first one by eye.
DUPLICATE_CASES = [
    ("two distinct keys", ['"a" = "1";', '"b" = "2";'], []),
    ("the same key twice", ['"a" = "1";', '"a" = "2";'], [("a", 2)]),
    ("a key three times", ['"a" = "1";', '"a" = "2";', '"a" = "3";'], [("a", 3)]),
]

SYMMETRY_CASES = [
    ("identical tables", ["a", "b"], ["a", "b"], ([], [])),
    ("a key only english declares", ["a", "b"], ["a"], (["b"], [])),
    ("a key only chinese declares", ["a"], ["a", "b"], ([], ["b"])),
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
    for name, source, expected in LOG_ROW_CASES:
        found = keys_in_source(source)
        check(found == expected, "log row scan %s %s" %
              ("finds" if found == expected else "got %s, expected %s for" %
               (sorted(found), sorted(expected)), name))
    for name, source, expected in ROW_SHAPES:
        found = unreadable_rows(source)
        ok = found == expected
        verdict = ("%s %s" % ("refuses" if expected else "accepts", name)) if ok else \
            ("got %s, expected %s for %s" % (found, expected, name))
        check(ok, "log row shape " + verdict)
    for name, source, expected in ARITY_CASES:
        found = bad_mlstring_arity(source)
        ok = found == expected
        verdict = ("%s %s" % ("refuses" if expected else "accepts", name)) if ok else \
            ("got %s, expected %s for %s" % (found, expected, name))
        check(ok, "macro arity " + verdict)
    for name, table_text, expected in DUPLICATE_CASES:
        found = duplicate_keys_in_text("\n".join(table_text))
        ok = found == expected
        check(ok, "duplicate key check %s %s" %
              ("reports" if ok else "got %s, expected %s for" % (found, expected), name))
    for name, en_names, zh_names, expected in SYMMETRY_CASES:
        found = table_symmetry(en_names, zh_names)
        ok = found == expected
        check(ok, "table symmetry %s %s" %
              ("reports" if ok else "got %s, expected %s for" % (found, expected), name))


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

dup_en = duplicate_keys(raw_en)
dup_zh = duplicate_keys(raw_zh)
for label, table, dups in (("en", EN_TABLE, dup_en), ("zh-Hans", ZH_TABLE, dup_zh)):
    for key, count in dups:
        print("::error file=%s::key is declared %d times, only the last entry is live: %s"
              % (table, count, key))
check(not dup_en and not dup_zh,
      "neither language table declares a key twice"
      if not (dup_en or dup_zh) else
      "repeated table keys: english %d, chinese %d" % (len(dup_en), len(dup_zh)))

only_en, only_zh = table_symmetry(raw_en, raw_zh)
for table, keys in ((EN_TABLE, only_en), (ZH_TABLE, only_zh)):
    for key in keys:
        print("::error file=%s::this table declares a key the other language does not: %s"
              % (table, key))
check(not only_en and not only_zh,
      "the two language tables declare the same set of keys"
      if not (only_en or only_zh) else
      "asymmetric table keys: english-only %d, chinese-only %d" % (len(only_en), len(only_zh)))

hidden_keys = []
for path, text in source_texts(root):
    if "MLLogRow(" not in text:
        continue
    for hidden in unreadable_rows(text):
        print("::error file=%s::a log row hides a translatable half behind a value the "
              "scan cannot read: %s" % (path, hidden))
    hidden_keys += unreadable_rows(text)
check(not hidden_keys, "every log row names its category and sentence where the scan can "
      "read them" if not hidden_keys else
      "log rows whose keys no scan can see: %d" % len(hidden_keys))

arity_problems = []
for path, text in source_texts(root):
    if "MLString" not in text:
        continue
    for problem in bad_mlstring_arity(text):
        print("::error file=%s::MLString is a two-argument macro, this call has %s"
              % (path, problem))
        arity_problems.append(problem)
check(not arity_problems, "every MLString call matches the macro the header defines"
      if not arity_problems else
      "MLString calls with the wrong number of arguments: %d" % len(arity_problems))

# The scan and its health rule are the whole value of this audit, so they are
# tested here rather than assumed: an audit that cannot tell a clean tree from a
# blind scanner is not a gate.
self_test()

print("%d localization failures" % len(failures))
sys.exit(1 if failures else 0)
