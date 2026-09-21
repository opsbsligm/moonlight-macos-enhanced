#!/usr/bin/env python3
"""Report localization keys that the UI can ask for but no layer can answer.

There is one table per language: the .strings file in the bundle. LanguageManager
used to carry two Swift dictionaries as well, consulted first, which made a
hundred rows of the shipped tables dead text and put another hundred outside the
shipped-image audit entirely. Those dictionaries are deleted and a rule refuses
them coming back, so a key missing here is a key that renders as itself.

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
import io, os, plistlib, re, sys

positional = [a for a in sys.argv[1:] if not a.startswith("--")]
root = positional[0] if positional else "."

lm_path = os.path.join(root, "Limelight/macOS/Helpers/LanguageManager.swift")
lm = io.open(lm_path, encoding="utf-8").read()

KEY_LINE = re.compile(r'^"((?:[^"\\]|\\.)+)"\s*=', re.M)


def strings_key_list(path):
    """Every key a .strings table declares, in file order, repeats included."""
    if not os.path.exists(path):
        return []
    return KEY_LINE.findall(io.open(path, encoding="utf-8").read())


def strings_values(path):
    """Every key and value a .strings table declares, in the file's own escaping."""
    if not os.path.exists(path):
        return {}
    return dict(re.findall(r'^"((?:[^"\\]|\\.)+)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;',
                           io.open(path, encoding="utf-8").read(), re.M))


def walk_table(text):
    """Every entry a .strings table declares, with the two lines it spans.

    A .strings table is an OpenStep plist. Nothing in it requires one entry per
    line, and a string literal may carry a real newline, so both "two entries on one
    line" and "one entry across three lines" are legal to CoreFoundation. The audit's
    own reader is line anchored, so an entry that does not begin a line, or does not
    end one, is invisible to every rule below: coverage, symmetry and placeholders
    would all wave it through, which is how `Clipboard Sync detail` sat in the en
    table uncounted while the app translated it correctly. Parsing the table the way
    the parser does makes the two views comparable.
    """
    entries = []
    i, n, line = 0, len(text), 1

    def skip_string():
        """Walk past a string literal opened at i, returning its body and end line."""
        nonlocal i, line
        i += 1
        start = i
        while i < n and text[i] != '"':
            if text[i] == "\\":
                i += 2
            else:
                if text[i] == "\n":
                    line += 1
                i += 1
        return text[start:i], line

    while i < n:
        char = text[i]
        if char == "\n":
            i += 1
            line += 1
            continue
        if char in " \t\r":
            i += 1
            continue
        if text.startswith("//", i):
            i = text.find("\n", i)
            i = n if i < 0 else i
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                break
            line += text.count("\n", i, end + 2)
            i = end + 2
            continue
        if char != '"':
            break
        start_line = line
        key, _ = skip_string()
        i += 1
        while i < n and text[i] in " \t\r\n":
            line += text[i] == "\n"
            i += 1
        if i >= n or text[i] != "=":
            break
        i += 1
        while i < n and text[i] in " \t\r\n":
            line += text[i] == "\n"
            i += 1
        if i >= n or text[i] != '"':
            break
        _, value_end_line = skip_string()
        i += 1
        while i < n and text[i] in " \t\r\n":
            line += text[i] == "\n"
            i += 1
        terminated = i < n and text[i] == ";"
        if terminated:
            i += 1
        entries.append((key, start_line, value_end_line, terminated))
    return entries


def entries_missing_a_terminator(text):
    """Entries whose value is never closed by a semicolon, with the line each begins on.

    An entry with no semicolon is not a table entry; CoreFoundation stops reading the
    table where the syntax stops. Reading past it -- which is what a lenient parser
    does, and what this one did until a two-line insertion loses its semicolon and
    shipped -- makes the broken row look like two good ones, so the entry count, the
    symmetry check and the coverage check all agree with each other and disagree with
    the app. That insertion was caught by `plutil -lint`, not by this audit.
    """
    return [(key, start) for key, start, _, terminated in walk_table(text) if not terminated]


def string_entries(text):
    """Every entry a .strings table declares, with the two lines it spans."""
    return [(key, start, end) for key, start, end, _ in walk_table(text)]


def entries_the_line_scan_cannot_see(text):
    """Entries the parser reads that a line-anchored scan of the same text does not.

    Either shape is enough to hide one: the entry that shares a line with the one
    above it never matches `^"key" =`, and the entry whose value carries a real
    newline is only half inside any line.
    """
    anchored = {text.count("\n", 0, m.start()) + 1 for m in KEY_LINE.finditer(text)}
    hidden, claimed = [], set()
    for key, start, end in string_entries(text):
        # `^` matches once per line at most, so the first entry of a line is the only
        # one an anchored scan can reach, and only when it really begins the line.
        if end != start or start not in anchored or start in claimed:
            hidden.append((key, start, end))
        else:
            claimed.add(start)
    return hidden


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


def info_plist_localization(files_by_directory):
    # An InfoPlist.strings localizes the Info.plist that sits beside it and nothing else.
    # Xcode reads it as that plist's language variant instead of copying it as a resource,
    # so the same file parked somewhere else in the tree yields no artifact, breaks no build,
    # and fails no gate: the permission sentences stay in English on a Chinese system while
    # every table in this repository stays green. Both halves of that silence get refused --
    # the file outside a language folder, and a language folder with no plist beside it.
    problems = []
    for directory in sorted(files_by_directory):
        if "InfoPlist.strings" not in files_by_directory[directory]:
            continue
        parent, language = os.path.split(directory)
        if not language.endswith(".lproj"):
            problems.append("%s is not inside a language folder" % directory)
        elif "Info.plist" not in files_by_directory[parent]:
            problems.append("%s has no Info.plist beside it to localize" % language)
    return problems


def usage_description_problems(descriptions, en_meta, zh_meta):
    # macOS shows a permission sentence from the plist, in the system language, so Chinese
    # written into the plist is not a translation of anything: it is what an English system
    # is made to display. The translation belongs in the Info.plist table beside that plist,
    # and a sentence answered by one of those tables and not the other is the same one-sided
    # drift the two main tables already refuse. A sentence no table answers stays English on
    # every system, which is untranslated but honest, so it is not reported here.
    problems = []
    for key in sorted(descriptions):
        if any(ord(character) > 127 for character in descriptions[key]):
            problems.append("%s is written into the plist in a language other than the "
                            "development region" % key)
        if (key in en_meta) != (key in zh_meta):
            problems.append("%s is answered by one Info.plist table and not the other" % key)
    return problems


def usage_descriptions(scan_root):
    plist = os.path.join(scan_root, "Limelight", "macOS", "Supporting Files", "Info.plist")
    if not os.path.exists(plist):
        return {}
    with open(plist, "rb") as handle:
        values = plistlib.load(handle)
    return {key: value for key, value in values.items()
            if key.endswith("UsageDescription") and isinstance(value, str)}


def info_plist_layout(scan_root):
    files = {}
    for directory, _, names in os.walk(os.path.join(scan_root, "Limelight")):
        files[directory] = set(names)
    return files


INFO_PLIST = "Limelight/macOS/Supporting Files/Info.plist"
INFO_META_EN = "Limelight/macOS/Supporting Files/en.lproj/InfoPlist.strings"
INFO_META_ZH = "Limelight/macOS/Supporting Files/zh-Hans.lproj/InfoPlist.strings"

EN_TABLE = "Limelight/macOS/en.lproj/Localizable.strings"
ZH_TABLE = "Limelight/macOS/zh-Hans.lproj/Localizable.strings"

# The lists are read once and reused: the set is what answers a key, the list is
# what shows a key being declared twice or on one side only.
raw_en = strings_key_list(os.path.join(root, EN_TABLE))
raw_zh = strings_key_list(os.path.join(root, ZH_TABLE))

en, zh = set(raw_en), set(raw_zh)

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


# Two more ways a key reaches a table without ever appearing inside a call the scanner
# reads: a computed property whose name ends in Key returns it, and an enum's displayKey
# returns it. Both arrive at localize() as a variable, so the literal sits nowhere near a
# call site. A setting's option label and its explanatory sentence reach the table exactly
# this way, which is how one of each lost their entries and stayed green -- the picker asked
# for a name no table answered, and the scan reported complete coverage.
KEY_PROPERTY = re.compile(
    r'var\s+\w*Key\s*:\s*String\s*\{[^{}]*?return\s+"((?:[^"\\]|\\.)+)"', re.S)
DISPLAY_KEY_BODY = re.compile(r'var\s+displayKey\s*:\s*String\s*\{(.*?)\n\s*\}', re.S)


def keys_carried_by_names(text):
    """Keys a variable carries to localize(), where no call site shows them.

    Deliberately narrow. A property whose body holds braces is skipped rather than guessed
    at, because a scan that invents keys would fail a clean tree, and this audit has already
    learned that a green tick from a scan checking nothing is worse than a red one. What it
    does read are the two shapes the settings panes actually use.
    """
    keys = set(KEY_PROPERTY.findall(text))
    for body in DISPLAY_KEY_BODY.findall(text):
        keys |= set(re.findall(r'return\s+"((?:[^"\\]|\\.)+)"', body))
    return keys


# A fourth shape, and the one issue #30 left behind: a descriptor that stores the key
# where it used to store the sentence. Nothing about `nameKey: "Discovery"` looks like a
# localization call, yet the value is looked up by exactly one, so a table that stops
# answering it makes the panel print "Discovery · mDNS" -- English by accident -- with
# this scan reporting complete coverage. Named outlets only: `filterKey:` and
# `categoryKey:` in the same file carry log keys that must never be translated.
KEY_ARGUMENT = re.compile(
    r'\b(?:nameKey|badgeKey|titleKey|labelKey|textKey)\s*:\s*@?"((?:[^"\\\n]|\\.)+)"')


# A fifth shape, and the one that paid off the last of the log panel's translation debt:
# the parser hands `title:` and `detail:` a key and SettingsAppPane localises it where the
# row renders. No call site sits near those literals, so a key no table answers would read
# as source text in both languages and this scan would report complete coverage.
# Scoped to the one file that works that way: `FormCell(title:)` localises inside its own
# initialiser, and reading every `title:` in the settings panes would only duplicate the
# call scanner that already covers them. A literal carrying an escape -- an interpolated
# host name, a code -- is data rather than a key, so it is left out.
LOG_PRESENTATION_ARGUMENT = re.compile(r'\b(?:title|detail)\s*:\s*@?"((?:[^"\\\n]|\\.)+)"')
LOG_PRESENTATION_FILES = ("Limelight/macOS/ViewControllers/DebugLogParser.swift",)


def keys_handed_to_a_row(relative_path, text):
    """The key literals a log row carries to the view that translates them."""
    if relative_path not in LOG_PRESENTATION_FILES:
        return set()
    return {key for key in LOG_PRESENTATION_ARGUMENT.findall(text) if "\\" not in key}


def keys_in_source(text):
    """The keys one source file asks the localization layers for."""
    return {match.group(1) for match in CALL_PATTERN.finditer(text) if match.group(1)} \
        | log_row_keys(text) | keys_carried_by_names(text) | set(KEY_ARGUMENT.findall(text))


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
    for path, text in source_texts(scan_root):
        relative = os.path.relpath(path, scan_root).replace(os.sep, "/")
        used |= keys_in_source(text) | keys_handed_to_a_row(relative, text)
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


# Issue #30: the log panel rewrites English log lines into Chinese, and its category
# menu and badges were written in Chinese too, so an English system showed Chinese
# where the app had text and English where it had a key.
#
# The rule is deliberately about the *outlet*, not about the characters. Chinese inside
# a log-matching pattern is data -- 55 literals in the parser are strings it compares
# incoming log lines against, and translating one of those breaks the match rather than
# the language. So only a literal arriving at a named UI parameter or inside Text() is
# asked to be a key, which is the shape the panel actually uses to show a string.
UI_OUTLET_NAMES = ("displayName", "badgeText", "title", "detail", "label", "placeholder",
                   "badge", "messageText", "informativeText")
UI_OUTLET = re.compile(r'\b(?:%s)\s*:\s*@?"((?:[^"\\\n]|\\.)+)"' % "|".join(UI_OUTLET_NAMES))
TEXT_OUTLET = re.compile(r'\bText\(\s*@?"((?:[^"\\\n]|\\.)+)"')


def is_chinese(text):
    return any("\u4e00" <= character <= "\u9fff" for character in text)


def chinese_at_outlets(text):
    """Literals the code hands to a place a player reads, in one language only."""
    return [match.group(1) for pattern in (UI_OUTLET, TEXT_OUTLET)
            for match in pattern.finditer(text) if is_chinese(match.group(1))]


# A log body is data rather than UI: DebugLogParser matches on it, NoiseSummaryNames folds
# repeats of it, and a Chinese user who files an issue pastes it to a maintainer. Translating
# it therefore breaks the match and the report at the same time, and PR #44 asked for exactly
# that. The tree was cleaned of the last five of these (`Help -> 诊断连接问题` in three
# discovery errors, which also named a menu item that reads differently in each language), and
# this is what keeps them out.
#
# CJK rather than "non-ASCII" on purpose: an em dash or an arrow in an English log line is
# typography, it arrives from the source rather than from a language table, and a rule that
# refused it would be a rule this repo has no intention of enforcing.
LOG_CALLS = ("Log(", "LogTagv(", "NSLog(")


def log_bodies_in_a_spoken_language(text):
    """Literals a log call prints in a language rather than as data."""
    bad = []
    for token in LOG_CALLS:
        index = text.find(token)
        while index >= 0:
            after = index + len(token)
            index = text.find(token, after)
            if text[:after - len(token)].rstrip().endswith("#define"):
                continue  # the macro definition, whose parameters are not bodies
            for argument in top_level_arguments(text, after):
                for literal in STRING_LITERAL.findall(argument):
                    # A sentence behind a translation call is a key, and keys are the
                    # tables' business; this rule is about text printed as it was written.
                    if any(token in argument for token in CALL_TOKENS) and "String(" not in argument:
                        continue
                    if is_chinese(literal) or any("\u3000" <= char <= "\u303f"
                                                 or "\uff00" <= char <= "\uffef" for char in literal):
                        bad.append("line %d: %s" % (text.count("\n", 0, after) + 1, literal[:40]))
    return bad


# One table per language, in the bundle, and nowhere else.
#
# LanguageManager carried two Swift dictionaries answering 227 keys, and localize() asked
# them first. That made 21 Chinese and 6 English rows in the .strings tables text no user
# ever saw; it left 131 sentences as the one part of the localisation that
# scripts/dmg-audit.py never read, because the image audit reads the tables inside the
# image and this file is not one of them; and it meant the log panel's filter box -- which
# indexes the .strings tables -- indexed sentences the UI never showed, so a player could
# copy a phrase off the screen and not find it. The dictionaries are deleted. This refuses
# them coming back, because the bug was the second table, not its contents.
INLINE_DICTIONARY = re.compile(r"private let (?:en|zhHans):\s*\[String:\s*String\]")


def inline_dictionaries(text):
    """Dictionaries that would answer keys ahead of the shipped tables."""
    return INLINE_DICTIONARY.findall(text)


# A row in the Chinese table that says no Chinese is one of two things: a proper noun or a
# token a player searches for verbatim, or a translation nobody did. The tree holds sixteen
# of the first and none of the second, and the difference is invisible from the outside --
# both read as English -- so the sixteen are named and anything else is refused. A missing
# translation that looks like a product name is exactly how a key reaches a screen.
TRANSLATED_BY_CHOICE = {
    "%@: %@", "1% Low", "AV1", "CoreHID", "GameController", "Geforce Experience", "HID",
    "HLG", "MFI", "MFi", "MetalFX", "Moonlight", "NSURLError %@", "PQ", "UUID", "Wi-Fi",
}


def chinese_rows_that_answer_in_english(rows):
    """Chinese rows whose value a Chinese player cannot read as Chinese."""
    return sorted(key for key, value in rows.items()
                  if not is_chinese(value) and key not in TRANSLATED_BY_CHOICE)


# Both tables have to answer a format string with the same placeholders. `String(format:)`
# is how the log panel fills in an error code or a retry count, and a table that drops the
# `%@` reads as a sentence with the number missing while the one that adds a second one
# hands a format string more arguments than it asks for.
PLACEHOLDER = re.compile(r"%(?:\d+\$)?(?:lld|llu|llx|ld|lu|lx|lf|ls|[@dDuUiIsSfFxXqEecgGn%])")


def placeholder_mismatches(en_rows, zh_rows):
    """Keys the two languages answer with different format specifiers."""
    found = []
    for key, value in en_rows.items():
        other = zh_rows.get(key)
        if other is None:
            continue
        mine, theirs = sorted(PLACEHOLDER.findall(value)), sorted(PLACEHOLDER.findall(other))
        if mine != theirs:
            found.append("%s: english %s, chinese %s" % (key[:48], mine, theirs))
    return found


# Characters that look like another one. Nine Chinese rows wrote `Wi-Fi` with a
# non-breaking hyphen, so a player who copied the phrase got a string that no search box,
# log file or issue thread matches the ASCII word against -- and nobody could tell by
# looking. NBSP, soft hyphens and zero-width joins are the same bug in another costume.
LOOKALIKES = {u"\u00a0": "no-break space", u"\u2011": "non-breaking hyphen",
              u"\u200b": "zero-width space", u"\u2060": "word joiner",
              u"\ufeff": "byte order mark", u"\u00ad": "soft hyphen",
              u"\u3000": "ideographic space"}


def lookalike_characters(tables):
    """Rows whose text hides a character that reads as a plainer one."""
    found = []
    for name, rows in tables:
        for key, value in sorted(rows.items()):
            for char, label in LOOKALIKES.items():
                if char in value or char in key:
                    found.append("%s: %s in %s" % (name, label, key[:48]))
    return found


# One entry per file, and the number is a ceiling rather than a statement. Every
# Chinese string still written at an outlet is a translation nobody has done yet, and
# the honest version of that is a list the next change has to shrink: the audit refuses
# a file that grows past its own number and refuses to leave the number sitting above
# what the tree now holds. That is the difference between a debt being recorded and a
# debt being paid down -- issue #30's first commit moved 24 of these into tables, and a
# plain "no Chinese literals anywhere" rule would have been switched off within a week.
# Empty, and it has to stay that way. The 55 this recorded were the log panel's titles and
# details, which the parser wrote in Chinese; they are keys now, so every literal that
# reaches a place a player reads is either a table key or a view literal in the development
# language. The dictionary is kept rather than deleted because the check below reads it: a
# file listed here is a debt somebody decided to carry, and carrying none is the rule.
UNTRANSLATED_OUTLETS = {}



def untranslated_outlets(scan_root):
    """Per file, the Chinese literals still written where a player will read them."""
    found = {}
    for directory, _, names in os.walk(os.path.join(scan_root, "Limelight")):
        for name in sorted(names):
            if not name.endswith(SOURCE_SUFFIXES):
                continue
            path = os.path.join(directory, name)
            relative = os.path.relpath(path, scan_root).replace(os.sep, "/")
            counted = []
            for line in io.open(path, encoding="utf-8", errors="replace").read().splitlines():
                if re.match(r"^\s*(//|\*|/\*)", line):
                    continue
                counted += chinese_at_outlets(line)
            if counted:
                found[relative] = len(counted)
    return found


# The Chinese branch of localize() must not answer with the key. `LanguageManager` reads
# the English table last, so a missing Simplified Chinese entry shows the player a
# sentence in the development language; answering with the key instead shows them the
# source identifier. That difference is invisible to every other rule here -- the key is
# in both tables, so coverage is satisfied -- which is why it is checked as a shape.
CHINESE_BRANCH = re.compile(r'if useChinese \{(?P<body>.*?)\n    \}', re.S)


def chinese_branch_answers_with_the_key(text):
    for match in CHINESE_BRANCH.finditer(text):
        if re.search(r'return\s+key\s*$', match.group("body"), re.M):
            return True
    return False


LANGUAGE_MANAGER = "Limelight/macOS/Helpers/LanguageManager.swift"


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
    ("a descriptor that stores the key",
     'nameKey: "Discovery \u00b7 mDNS",\n      badgeKey: "Discovery/mDNS"',
     {"Discovery \u00b7 mDNS", "Discovery/mDNS"}),
    ("a key that names a log category, not a sentence",
     'categoryKey: "discovery.mdns", filterKey: "network"', set()),
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

# The two shapes a call site never shows. The first is a setting's explanatory sentence, the
# second the label of a picker's option. A property that merely returns English is not a key
# and must not be scanned as one, or a clean tree starts failing for text never meant for a
# table.
FIXTURES += [
    ("a key a *Key property returns",
     'private var selectedKeyboardTranslationDetailKey: String {\n'
     '    return "Keyboard Compatibility Streaming Standard detail"\n  }',
     {"Keyboard Compatibility Streaming Standard detail"}),
    ("an option label an enum displayKey returns",
     'var displayKey: String {\n'
     '    switch self {\n'
     '    case .streamingStandard:\n'
     '      return "Streaming Standard (Recommended)"\n'
     '    }\n  }',
     {"Streaming Standard (Recommended)"}),
    ("a property that only returns English",
     'private var titleText: String {\n    return "Some English sentence"\n  }',
     set()),
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

# The shape that hides an entry from the audit: one entry riding on the line of the
# entry above it, and one entry whose value carries a real newline.
TERMINATOR_CASES = [
    ("both rows closed", ['"a" = "1";', '"b" = "2";'], []),
    ("a row that forgets the semicolon", ['"a" = "1"', '"b" = "2";'], [("a", 1)]),
    ("the last row forgets it", ['"a" = "1";', '"b" = "2"'], [("b", 2)]),
]

ENTRY_SHAPE_CASES = [
    ("one entry per line", ['"a" = "1";', '"b" = "2";'], []),
    ("the second entry rides on the first line",
     ['"a" = "1";"b" = "2";'], ["b"]),
    ("a value that carries a real newline",
     ['"a" = "one', 'two";'], ["a"]),
    ("a comment line, which is not an entry",
     ['// "a" = "1";', '"b" = "2";'], []),
]

SYMMETRY_CASES = [
    ("identical tables", ["a", "b"], ["a", "b"], ([], [])),
    ("a key only english declares", ["a", "b"], ["a"], (["b"], [])),
    ("a key only chinese declares", ["a"], ["a", "b"], ([], ["b"])),
]

USAGE_CASES = [
    ("an english plist sentence with both tables answering it",
     {"NSMicrophoneUsageDescription": "Used to capture microphone audio."},
     {"NSMicrophoneUsageDescription"}, {"NSMicrophoneUsageDescription"}, True),
    ("a chinese sentence written into the plist itself",
     {"NSLocalNetworkUsageDescription": "Moonlight需要访问本地网络。"},
     {"NSLocalNetworkUsageDescription"}, {"NSLocalNetworkUsageDescription"}, False),
    ("a permission translated on one side only",
     {"NSMicrophoneUsageDescription": "Used to capture microphone audio."},
     {"NSMicrophoneUsageDescription"}, set(), False),
    ("a permission nobody translates stays english on every system",
     {"NSCameraUsageDescription": "Used to capture video."}, set(), set(), True),
]

LOC_META_CASES = [
    ("a language folder beside the plist it localizes",
     {"/p": {"Info.plist"}, "/p/en.lproj": {"InfoPlist.strings"}}, True),
    ("a language folder with no plist beside it",
     {"/p": set(), "/p/en.lproj": {"InfoPlist.strings"}}, False),
    ("the file parked outside any language folder",
     {"/p": {"Info.plist", "InfoPlist.strings"}}, False),
    ("a localizable table anywhere is none of this rule",
     {"/p": set(), "/p/en.lproj": {"Localizable.strings"}}, True),
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
    for name, table_lines, expected in TERMINATOR_CASES:
        found = entries_missing_a_terminator("\n".join(table_lines))
        ok = found == expected
        check(ok, "terminator rule %s %s" %
              ("refuses" if expected else "accepts", name) if ok else
              "terminator rule got %s for %s" % (found, name))

    for name, table_lines, expected in ENTRY_SHAPE_CASES:
        found = [key for key, _, _ in
                 entries_the_line_scan_cannot_see("\n".join(table_lines))]
        ok = found == expected
        check(ok, "entry shape %s %s" %
              ("refuses" if expected else "accepts", name) if ok else
              "entry shape %s for %s (got %s)" %
              ("missed" if expected else "wrongly refused", name, found))

    for name, en_names, zh_names, expected in SYMMETRY_CASES:
        found = table_symmetry(en_names, zh_names)
        ok = found == expected
        check(ok, "table symmetry %s %s" %
              ("reports" if ok else "got %s, expected %s for" % (found, expected), name))
    for name, descriptions, en_meta, zh_meta, must_pass in USAGE_CASES:
        found = usage_description_problems(descriptions, en_meta, zh_meta)
        ok = bool(found) != must_pass
        check(ok, "usage descriptions %s %s" %
              ("accepts" if must_pass else "refuses", name) if ok else
              "usage descriptions %s: %s for %s" %
              ("missed" if not must_pass else "wrongly refused", found, name))

    OUTLET_CASES = [
        ("a badge written in Chinese", 'badgeText: "\u53d1\u73b0"', True),
        ("a bilingual category name", 'displayName: "\u53d1\u73b0 / Discovery"', True),
        ("a view literal", 'Text("\u4e32\u6d41")', True),
        ("the same text behind a key", 'nameKey: "Discovery"', False),
        ("Chinese inside a log pattern, which is data",
         'containsAny(line, ["\u6b63\u5728\u8fde\u63a5"])', False),
        ("a parameter that names a log category", 'categoryKey: "\u53d1\u73b0"', False),
    ]
    for name, source, must_fail in OUTLET_CASES:
        found = bool(chinese_at_outlets(source))
        ok = found == must_fail
        check(ok, "outlet rule %s %s" %
              ("refuses" if must_fail else "accepts", name) if ok else
              "outlet rule %s for %s" % ("missed" if not found else "wrongly refused", name))

    POINTS_CASES = [
        ("a row title held as a key", LOG_PRESENTATION_FILES[0],
         'return .init(title: "Stream stopped", detail: cleaned)', {"Stream stopped"}),
        ("a row detail held as a key", LOG_PRESENTATION_FILES[0],
         'return .init(title: "Stream stopped", detail: "App list retrieved")',
         {"Stream stopped", "App list retrieved"}),
        ("a row title assembled from captured data", LOG_PRESENTATION_FILES[0],
         'return .init(title: "Resolved a host address", detail: "\\(captures[0]) -> \\(captures[1])")',
         {"Resolved a host address"}),
        ("the same title in a pane that localises inside its own cell",
         "Limelight/macOS/ViewControllers/SettingsStreamPane.swift",
         'FormCell(title: "General") { }', set()),
    ]
    INLINE_CASES = [
        ("a dictionary that came back",
         'class X {\n  private let en: [String: String] = [\n    "Stream": "Stream",\n  ]\n}', True),
        ("the file as it ships, with no dictionary", 'public func localize(_ key: String) -> String { }', False),
    ]
    for name, source, must_fail in INLINE_CASES:
        found = bool(inline_dictionaries(source))
        ok = found == must_fail
        check(ok, "inline table rule %s %s" %
              ("refuses" if must_fail else "accepts", name) if ok else
              "inline table rule %s for %s" % ("missed" if not found else "wrongly refused", name))

    CHOICE_CASES = [
        ("an unregistered English answer", {"Resolution": "Resolution"}, True),
        ("a name a player searches verbatim", {"MetalFX": "MetalFX"}, False),
        ("a row that does say Chinese", {"Resolution": "\u5206\u8fa8\u7387"}, False),
    ]
    for name, rows, must_fail in CHOICE_CASES:
        found = bool(chinese_rows_that_answer_in_english(rows))
        ok = found == must_fail
        check(ok, "translated-by-choice rule %s %s" %
              ("refuses" if must_fail else "accepts", name) if ok else
              "translated-by-choice rule %s for %s" % ("missed" if not found else "wrongly refused", name))

    PH_CASES = [
        ("a Chinese row that dropped the placeholder",
         {"Error code %@": "Error code %@"}, {"Error code %@": "\u9519\u8bef\u7801"}, True),
        ("both rows carrying the placeholder",
         {"Error code %@": "Error code %@"}, {"Error code %@": "\u9519\u8bef\u7801 %@"}, False),
        ("a literal percent the other side reads as an argument",
         {"Done 100%@": "Done 100%@"}, {"Done 100%@": "\u5b8c\u6210 100%%"}, True),
    ]
    for name, e, z, must_fail in PH_CASES:
        found = bool(placeholder_mismatches(e, z))
        ok = found == must_fail
        check(ok, "placeholder rule %s %s" %
              ("refuses" if must_fail else "accepts", name) if ok else
              "placeholder rule %s for %s" % ("missed" if not found else "wrongly refused", name))

    LOOKALIKE_CASES = [
        ("a non-breaking hyphen in Wi-Fi", {"Wi-Fi": "Wi\u2011Fi"}, True),
        ("an ordinary hyphen", {"Wi-Fi": "Wi-Fi"}, False),
        ("a no-break space", {"Resolution": "\u5206\u8fa8\u7387\u00a0\u8bbe\u7f6e"}, True),
    ]
    for name, rows, must_fail in LOOKALIKE_CASES:
        found = bool(lookalike_characters([("table", rows)]))
        ok = found == must_fail
        check(ok, "lookalike rule %s %s" %
              ("refuses" if must_fail else "accepts", name) if ok else
              "lookalike rule %s for %s" % ("missed" if not found else "wrongly refused", name))

    LOG_BODY_CASES = [
        ("a Chinese sentence written into a log", 'Log(LOG_E, @"\u8fde\u63a5\u5931\u8d25");', True),
        ("an ASCII log line", 'Log(LOG_E, @"connection failed");', False),
        ("a sentence behind a translation call", 'Log(LOG_E, MLString(@"Connection Failed", nil));', False),
        ("a macro definition, whose parameters are not bodies",
         '#define Log(level, fmt, ...) LogTagv(level, @"", fmt, ##__VA_ARGS__)', False),
    ]
    for name, source, must_fail in LOG_BODY_CASES:
        found = bool(log_bodies_in_a_spoken_language(source))
        ok = found == must_fail
        check(ok, "log body rule %s %s" %
              ("refuses" if must_fail else "accepts", name) if ok else
              "log body rule %s for %s" % ("missed" if not found else "wrongly refused", name))

    for name, path, source, expected in POINTS_CASES:
        found = keys_handed_to_a_row(path, source)
        ok = found == expected
        check(ok, "row key scan %s %s" %
              ("finds" if ok else "got %s, expected %s for" % (sorted(found), sorted(expected)), name))

    for name, layout, must_pass in LOC_META_CASES:
        found = info_plist_localization(layout)
        ok = bool(found) != must_pass
        check(ok, "info plist layout %s %s" %
              ("accepts" if must_pass else "refuses", name) if ok else
              "info plist layout %s: %s for %s" %
              ("missed" if not must_pass else "wrongly refused", found, name))



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

# Before any rule reads a table, the audit and CoreFoundation have to be looking at
# the same number of entries. `Clipboard Sync detail` was in the en table the whole
# time, and translated correctly at runtime, while every rule above this one scored a
# table it had silently lost a row from.
for label, table in (("en", EN_TABLE), ("zh-Hans", ZH_TABLE)):
    path = os.path.join(root, table)
    text = io.open(path, encoding="utf-8").read()
    hidden = entries_the_line_scan_cannot_see(text)
    for key, start, end in hidden:
        print("::error file=%s::line %d carries an entry the line-anchored rules below cannot see: %s"
              % (table, start, key))
    check(not hidden, "every entry in the %s table is visible to the line-anchored rules" % label
          if not hidden else "%d entries in the %s table are invisible to its own rules"
          % (len(hidden), label))
    unterminated = entries_missing_a_terminator(text)
    for key, start in unterminated:
        print("::error file=%s::line %d ends an entry with no semicolon, and the table stops being read there: %s"
              % (table, start, key))
    check(not unterminated,
          "every entry in the %s table is closed by a semicolon" % label
          if not unterminated else
          "%d entries in the %s table have no terminator, and CoreFoundation stops at the first one"
          % (len(unterminated), label))
    parsed = string_entries(text)
    scanned = len(KEY_LINE.findall(text))
    check(len(parsed) == scanned,
          "the %s table parses into the same %d entries its rules read" % (label, scanned)
          if len(parsed) == scanned else
          "the %s table parses into %d entries while its rules read %d"
          % (label, len(parsed), scanned))

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

outlets = untranslated_outlets(root)
for path, count in sorted(outlets.items()):
    allowed = UNTRANSLATED_OUTLETS.get(path, 0)
    if count > allowed:
        print("::error file=%s::%d Chinese strings sit where a player reads them; "
              "the recorded debt for this file is %d: %s"
              % (path, count, allowed,
                 "none of them are recorded yet" if not allowed else "raise nothing, localize them"))
    elif count < allowed:
        print("::error file=%s::UNTRANSLATED_OUTLETS says %d, the tree now holds %d; "
              "a debt that is not lowered when it is paid stops meaning anything"
              % (path, allowed, count))
check(all(outlets.get(path, 0) == allowed for path, allowed in UNTRANSLATED_OUTLETS.items())
      and not [path for path in outlets if path not in UNTRANSLATED_OUTLETS],
      "no new untranslated text reaches a place a player reads, and no paid-down debt is left recorded"
      if all(outlets.get(path, 0) == allowed for path, allowed in UNTRANSLATED_OUTLETS.items())
      and not [path for path in outlets if path not in UNTRANSLATED_OUTLETS] else
      "untranslated UI text drifted: %s" % ", ".join(
          "%s=%d/%d" % (path, count, UNTRANSLATED_OUTLETS.get(path, 0))
          for path, count in sorted(outlets.items())))

log_bodies = []
for path, text in source_texts(root):
    if not any(token in text for token in LOG_CALLS):
        continue
    log_bodies += ["%s %s" % (os.path.basename(path), offender)
                   for offender in log_bodies_in_a_spoken_language(text)]
check(not log_bodies,
      "a log body is written as data, which is what lets the parser match it and a maintainer read it"
      if not log_bodies else
      "a log body was written in a language instead of as data: %s" % ", ".join(log_bodies[:8]))

check(not inline_dictionaries(lm),
      "one table per language, in the bundle: the second one used to shadow it and the image audit")

zh_rows = strings_values(os.path.join(root, "Limelight/macOS/zh-Hans.lproj/Localizable.strings"))
en_rows = strings_values(os.path.join(root, "Limelight/macOS/en.lproj/Localizable.strings"))
check(not chinese_rows_that_answer_in_english(zh_rows),
      "a Chinese row says Chinese, unless the row is a name or token a player searches verbatim"
      if not chinese_rows_that_answer_in_english(zh_rows) else
      "Chinese rows that answer in English, unregistered: %s"
      % ", ".join(chinese_rows_that_answer_in_english(zh_rows)[:8]))

check(not placeholder_mismatches(en_rows, zh_rows),
      "both tables answer a format string with the same placeholders, which is what String(format:) needs"
      if not placeholder_mismatches(en_rows, zh_rows) else
      "format placeholders differ between the tables: %s"
      % " | ".join(placeholder_mismatches(en_rows, zh_rows)[:4]))

check(not lookalike_characters([("chinese table", zh_rows), ("english table", en_rows)]),
      "no row hides a character that reads as a plainer one, which is what copying text off screen needs"
      if not lookalike_characters([("chinese table", zh_rows), ("english table", en_rows)]) else
      "lookalike characters in the tables: %s"
      % ", ".join(lookalike_characters([("chinese table", zh_rows), ("english table", en_rows)])[:6]))

check(not chinese_branch_answers_with_the_key(io.open(os.path.join(root, LANGUAGE_MANAGER),
                                                     encoding="utf-8", errors="replace").read()),
      "a missing Chinese entry falls back to the development language, never to the key")

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

descriptions = usage_descriptions(root)
meta_en = set(strings_key_list(INFO_META_EN)) if os.path.exists(os.path.join(root, INFO_META_EN)) else set()
meta_zh = set(strings_key_list(INFO_META_ZH)) if os.path.exists(os.path.join(root, INFO_META_ZH)) else set()
usage_problems = usage_description_problems(descriptions, meta_en, meta_zh)
for problem in usage_problems:
    print("::error file=%s::%s" % (INFO_PLIST, problem))
check(not usage_problems,
      "%d permission sentences stay translatable rather than baked into one language"
      % len(descriptions) if not usage_problems else
      "permission prompts no language can be shown correctly: " + "; ".join(usage_problems))

meta_problems = info_plist_localization(info_plist_layout(root))
check(not meta_problems, "the Info.plist language files sit where a build will read them"
      if not meta_problems else
      "Info.plist localizations no build will ever use: " + ", ".join(meta_problems))

# The scan and its health rule are the whole value of this audit, so they are
# tested here rather than assumed: an audit that cannot tell a clean tree from a
# blind scanner is not a gate.
self_test()

print("%d localization failures" % len(failures))
sys.exit(1 if failures else 0)
