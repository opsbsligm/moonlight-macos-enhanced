#!/usr/bin/env python3
"""Fail on a DMG that cannot be installed, and publish the bytes it hashed to.

Three things about a disk image are invisible to every other gate in this
repository. Whether the image still holds the bytes that were written -- the
artifact service, a re-download, and a release asset are three copies of a
10 MB file and nothing compared them; whether the image actually contains an
app a user can drag -- the packaging step in the workflow falls back from
create-dmg to a bare `hdiutil create` with `||`, which succeeds and produces an
image with no Applications link, so the drop target that makes a macOS install
work is simply gone and the job that built it stays green; and whether the
build number a release announces is the one inside the image the release hands
out.

`hdiutil verify` answers the first on a macOS host, mounting answers the
second, Info.plist answers the third, and the .sha256 sidecar lets the release
job -- which runs on ubuntu and cannot mount anything -- prove that the bytes it
is publishing are the bytes that were built.

A fourth question arrived with issue #44: whether the sentences a permission
prompt shows are translated in the build a user downloads. The tables are
installed by codesign-bundle.sh and read back from the bundle it signs, but the
image is packaged after that, and the universal merge writes over Resources -- so
the audit now requires the shipped image to carry every table the repository
holds, entry for entry.

The self-test builds its own images rather than trusting a fixture: a good one
has to pass, one without a drop target has to be rejected, a build number that
disagrees has to be rejected, and appended bytes have to be caught twice, once
by the image's own checksum and once by the sidecar.
"""
import argparse, hashlib, os, plistlib, re, shutil, subprocess, sys, tempfile

HDIUTIL = shutil.which("hdiutil") or "/usr/bin/hdiutil"
APP_NAME = "Moonlight.app"
BINARY = os.path.join("Contents", "MacOS", "Moonlight")
INFO = os.path.join("Contents", "Info.plist")
RESOURCES = os.path.join("Contents", "Resources")

# Where the repository keeps the tables that translate a permission prompt, and the
# rule by which the shipped copy is judged. codesign-bundle.sh installs these tables
# and reads them back from the bundle it is about to seal, which proves the bundle at
# signing time. The image is what a user downloads, and the steps between the two --
# the universal merge overwriting Resources, create-dmg's staging, any future
# re-pack -- can lose them with every job still green. The audit compares the shipped
# tables against the repository's own, so a translation that exists only in git is
# refused rather than announced.
SOURCE_LPROJ_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "Limelight", "macOS", "Supporting Files")
LOCALIZED_INFO = "InfoPlist.strings"

# A .strings table is the old-style plist, which plistlib does not read. Parsing the
# entries here rather than shelling out to plutil keeps the rule checkable on a host
# that has neither the tool nor the language.
ENTRY = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;', re.M)
ESCAPES = {r'\"': '"', r"\n": "\n", r"\\": "\\", r"\t": "\t"}


def unescape(text):
    for raw, decoded in ESCAPES.items():
        text = text.replace(raw, decoded)
    return text


def parse_strings(text):
    """The key/value pairs of an old-style .strings table."""
    return {unescape(key): unescape(value) for key, value in ENTRY.findall(text)}


def read_tables(directory):
    """Every <lang>.lproj/InfoPlist.strings under a directory, keyed by language."""
    tables = {}
    for base, _, files in os.walk(directory):
        if LOCALIZED_INFO not in files:
            continue
        language = os.path.basename(base)
        with open(os.path.join(base, LOCALIZED_INFO), "rb") as handle:
            tables[language] = parse_strings(handle.read().decode("utf-8"))
    return tables


def sha256_of(path, chunk=1 << 20):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def checksum_line(image):
    """`sha256sum` format: hash, two spaces, basename."""
    return "%s  %s\n" % (sha256_of(image), os.path.basename(image))


def write_checksum(image, directory=None):
    path = os.path.join(directory or os.path.dirname(image) or ".",
                        os.path.basename(image) + ".sha256")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(checksum_line(image))
    return path


def read_checksum(sidecars):
    """Map basename -> expected hash across one or more sidecar files."""
    wanted = {}
    for path in sidecars:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2 or len(parts[0]) not in (32, 64):
                raise SystemExit("error: %s has a line that is not a checksum line: %r"
                                 % (path, line))
            wanted[os.path.basename(parts[1].lstrip("*"))] = parts[0].lower()
    if not wanted:
        raise SystemExit("error: %s record no checksums, so nothing would be verified"
                         % ", ".join(sidecars))
    return wanted


def verify_checksums(sidecars, search_dirs):
    """Compare the bytes that are about to be published with the built bytes."""
    wanted = read_checksum(sidecars)
    found = {}
    for directory in search_dirs:
        for base, _, files in os.walk(directory):
            for name in files:
                if name in wanted and name not in found:
                    found[name] = os.path.join(base, name)
    problems = []
    for name, expected in sorted(wanted.items()):
        path = found.get(name)
        if path is None:
            problems.append("%s is listed in a checksum file and is not being published" % name)
            continue
        actual = sha256_of(path)
        if actual != expected:
            problems.append("%s was built as %s and is now %s" % (name, expected, actual))
        else:
            print("ok %s %s" % (actual, name))
    if problems:
        raise SystemExit("error: the bytes being published are not the bytes that were "
                         "built:\n  " + "\n  ".join(problems))
    return wanted


def hdiutil_verify(image):
    """Ask the image for its own checksum, which is not the same question as hashing the file."""
    if not os.path.exists(HDIUTIL):
        raise SystemExit("error: %s is missing, so the integrity of %s cannot be checked. "
                         "That is an environment problem, not a defect in the image."
                         % (HDIUTIL, image))
    result = subprocess.run([HDIUTIL, "verify", image], capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip().splitlines()
        raise SystemExit("error: %s failed its own checksum: %s"
                         % (image, detail[-1] if detail else "no reason given"))
    print("ok image checksum %s" % image)


class Mounted:
    """Mount a DMG read-only and hand back its mount point."""

    def __init__(self, image):
        self.image = image
        self.point = None

    def __enter__(self):
        holder = tempfile.mkdtemp(prefix="dmg-audit-")
        self.point = os.path.join(holder, "mnt")  # hdiutil wants it not to exist yet
        result = subprocess.run([HDIUTIL, "attach", "-readonly", "-nobrowse",
                                 "-mountpoint", self.point, self.image],
                                capture_output=True, text=True)
        if result.returncode != 0:
            detail = (result.stdout + result.stderr).strip().splitlines()
            raise SystemExit("error: %s could not be mounted: %s"
                             % (self.image, detail[-1] if detail else "no reason given"))
        return self.point

    def __exit__(self, *_):
        subprocess.run([HDIUTIL, "detach", "-force", self.point],
                       capture_output=True, text=True)
        shutil.rmtree(os.path.dirname(self.point), ignore_errors=True)


def localization_findings(app, info, tables):
    """Require the shipped image to carry every translated sentence the repository has.

    Three ways this rots, and each is a different failure: a table missing means the
    user reads the sentence baked into Info.plist in a language they did not choose; a
    table that differs from the source means the image and the repository tell two
    stories; a table for a language no source provides means a stale one survived a
    rename. The last one matters more than it looks: an empty or stale table still
    satisfies a gate that only counts files.

    Every key Info.plist asks a prompt to translate has to appear in every table. That
    is the shape of issue #44 -- one sentence left in Chinese inside the English plist,
    so an English system had nothing to fall back to but the source text.
    """
    problems = []
    if not tables:
        return ["no %s table under %s, so nothing can be required of the image"
                % (LOCALIZED_INFO, SOURCE_LPROJ_ROOT)]
    shipped = read_tables(os.path.join(app, RESOURCES))
    for language in sorted(tables):
        want = tables[language]
        got = shipped.get(language)
        if got is None:
            problems.append("%s carries no table for %s, so that language shows the "
                            "sentence written into Info.plist instead of its own"
                            % (APP_NAME, language))
            continue
        missing = sorted(set(want) - set(got))
        changed = sorted(key for key in set(want) & set(got) if want[key] != got[key])
        if missing:
            problems.append("the image's table for %s is missing %s, which the "
                            "repository translates" % (language, ", ".join(missing)))
        if changed:
            problems.append("the image's table for %s is not the table the repository "
                            "holds for %s" % (language, ", ".join(changed)))
    for language in sorted(set(shipped) - set(tables)):
        problems.append("the image carries a table for %s with none behind it in the "
                        "repository, so it is stale by construction" % language)
    prompts = sorted(key for key in info if key.endswith("UsageDescription"))
    for key in prompts:
        for language, table in sorted(shipped.items()):
            if not table.get(key):
                problems.append("the prompt for %s has no entry in %s, so that language "
                                "reads the plist's own sentence" % (key, language))
    if not problems:
        print("ok localized prompts %s (%s)"
              % (", ".join(sorted(shipped)),
                 ", ".join(prompts) if prompts else "no UsageDescription keys"))
    return problems


def inspect(image, version=None, build=None, tables=None):
    """Require the shape every installer needs, and report what is inside it."""
    problems = []
    with Mounted(image) as point:
        root = [p for p in os.listdir(point) if not p.startswith(".")]
        app = os.path.join(point, APP_NAME)
        if APP_NAME not in root:
            problems.append("%s is not at the root of the image; the root holds %s"
                            % (APP_NAME, ", ".join(sorted(root)) or "nothing"))
        elif not os.path.isfile(os.path.join(app, BINARY)):
            problems.append("%s has no %s, so nothing in the image launches"
                            % (APP_NAME, BINARY))
        else:
            plist = os.path.join(app, INFO)
            if not os.path.isfile(plist):
                problems.append("%s has no Info.plist, so its version cannot be read"
                                % APP_NAME)
            else:
                with open(plist, "rb") as handle:
                    info = plistlib.load(handle)
                mismatch = False
                for key, want in (("CFBundleShortVersionString", version),
                                  ("CFBundleVersion", build)):
                    got = str(info.get(key, ""))
                    if want is not None and got != str(want):
                        problems.append("the image carries %s=%s and the caller expects %s"
                                        % (key, got or "<absent>", want))
                        mismatch = True
                    elif want is None and not got:
                        problems.append("%s carries no %s, so a release cannot name the "
                                        "build it is publishing" % (APP_NAME, key))
                        mismatch = True
                if not mismatch:
                    print("ok bundle %s version %s build %s"
                          % (APP_NAME, info.get("CFBundleShortVersionString"),
                             info.get("CFBundleVersion")))
                if tables is not None:
                    problems += localization_findings(app, info, tables)
        # The link is the install gesture. An image made by the bare
        # `hdiutil create` fallback holds the app and nothing else: there is no
        # drop target, and no line in the build log says the package changed shape.
        link = os.path.join(point, "Applications")
        if not os.path.islink(link):
            problems.append("the image has no Applications link at its root, so it has no "
                            "drop target -- that is the shape the `hdiutil create` fallback "
                            "produces, not the create-dmg one. The root holds "
                            + ", ".join(sorted(root)))
        elif os.readlink(link) != "/Applications":
            problems.append("the image points Applications at %r instead of /Applications"
                            % os.readlink(link))
        else:
            print("ok drop target Applications -> /Applications")
    if problems:
        raise SystemExit("error: %s is not an installable package:\n  "
                         % image + "\n  ".join(problems))


def write_tables(directory, tables):
    """Write old-style tables for a fixture, in the shape the audit has to read back."""
    for language, entries in tables.items():
        folder = os.path.join(directory, language)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, LOCALIZED_INFO), "w", encoding="utf-8") as handle:
            handle.write("\n".join('"%s" = "%s";' % (key, value)
                                    for key, value in sorted(entries.items())) + "\n")


def build_image(staging, image, with_link, localizations=None, info=None):
    """Make a throwaway image for the self-test, with or without the drop target."""
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(os.path.join(staging, APP_NAME, "Contents", "MacOS"))
    binary = os.path.join(staging, APP_NAME, BINARY)
    with open(binary, "w") as handle:
        handle.write("#!/bin/sh\necho self-test\n")
    os.chmod(binary, 0o755)
    bundle_info = {"CFBundleIdentifier": "std.skyhua.MoonlightMac2",
                   "CFBundleName": "Moonlight",
                   "CFBundleShortVersionString": "9.9.9",
                   "CFBundleVersion": "1"}
    if info:
        bundle_info.update(info)
    with open(os.path.join(staging, APP_NAME, INFO), "wb") as handle:
        plistlib.dump(bundle_info, handle)
    if localizations:
        write_tables(os.path.join(staging, APP_NAME, RESOURCES), localizations)
    if with_link:
        os.symlink("/Applications", os.path.join(staging, "Applications"))
    result = subprocess.run([HDIUTIL, "create", "-volname", "self-test",
                             "-srcfolder", staging, "-ov", "-format", "UDZO", image],
                            capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip().splitlines()
        raise SystemExit("error: the self-test could not build an image to test: "
                         + (detail[-1] if detail else "no reason given"))


ABSOLUTE_PATH = re.compile(r"(/\S+)+")


def reason_for(message):
    """The rule a rejection states, with the self-test's temp prefix folded away."""
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    for line in lines:
        if line.endswith(":"):  # a header; the reason is on the lines under it
            continue
        folded = ABSOLUTE_PATH.sub(lambda match: os.path.basename(match.group(0)), line)
        folded = folded[len("error: "):] if folded.startswith("error: ") else folded
        return folded[:110]
    return (lines[0] if lines else "")[:110]


def expect_rejection(what, call):
    try:
        call()
    except SystemExit as failure:
        message = str(failure).strip()
        if not message:
            raise AssertionError("%s was rejected with no reason given" % what)
        print("rejects %s -- %s" % (what, reason_for(message)))
        return
    raise AssertionError("accepted %s; an image gate that accepts it is not a gate" % what)


def self_test():
    """A good image passes, and each of the ways one can be wrong is caught."""
    if not os.path.exists(HDIUTIL):
        raise SystemExit("error: %s is missing, so the image half of the self-test cannot "
                         "run. The checksum half is --self-test-checksums, which needs no "
                         "toolchain at all." % HDIUTIL)
    workspace = tempfile.mkdtemp(prefix="dmg-audit-selftest-")
    # The fixture stands in for the repository: two source tables, and an Info.plist
    # that asks one prompt to be translated. Expectations are read from the fixture
    # rather than written twice, so the self-test cannot drift from the rule.
    tables = {"en.lproj": {"NSMicrophoneUsageDescription": "Used to capture audio"},
              "zh-Hans.lproj": {"NSMicrophoneUsageDescription": "\u7528\u4e8e\u91c7\u96c6\u97f3\u9891"}}
    source = os.path.join(workspace, "source-tables")
    write_tables(source, tables)
    expected = read_tables(source)
    prompt = {"NSMicrophoneUsageDescription": "Used to capture audio"}
    try:
        good = os.path.join(workspace, "Moonlight-Enhanced.dmg")
        build_image(os.path.join(workspace, "staged-good"), good, with_link=True,
                    localizations=tables, info=prompt)
        inspect(good, version="9.9.9", build="1", tables=expected)
        hdiutil_verify(good)
        sidecar = write_checksum(good)
        verify_checksums([sidecar], [workspace])

        # Same app, packaged the way the workflow's `||` fallback packages it.
        bare = os.path.join(workspace, "no-drop-target.dmg")
        build_image(os.path.join(workspace, "staged-bare"), bare, with_link=False)
        expect_rejection("an image with no Applications link",
                         lambda: inspect(bare, version="9.9.9", build="1"))

        # The build number a tag announces versus the one inside the image.
        expect_rejection("an image whose build number disagrees",
                         lambda: inspect(good, version="9.9.9", build="2"))

        # The translation that lives in the repository but never reached the download.
        one_language = dict(tables)
        one_language.pop("zh-Hans.lproj")
        thin = os.path.join(workspace, "no-second-table.dmg")
        build_image(os.path.join(workspace, "staged-thin"), thin, with_link=True,
                    localizations=one_language, info=prompt)
        expect_rejection("an image that lost one language's prompt table",
                         lambda: inspect(thin, version="9.9.9", build="1", tables=expected))

        drifted = {"en.lproj": {"NSMicrophoneUsageDescription": "Used for something else"},
                   "zh-Hans.lproj": tables["zh-Hans.lproj"]}
        stale = os.path.join(workspace, "drifted-tables.dmg")
        build_image(os.path.join(workspace, "staged-drift"), stale, with_link=True,
                    localizations=drifted, info=prompt)
        expect_rejection("an image whose table is not the repository's",
                         lambda: inspect(stale, version="9.9.9", build="1", tables=expected))

        extra = dict(tables)
        extra["fr.lproj"] = {"NSMicrophoneUsageDescription": "stub"}
        orphan = os.path.join(workspace, "orphan-table.dmg")
        build_image(os.path.join(workspace, "staged-orphan"), orphan, with_link=True,
                    localizations=extra, info=prompt)
        expect_rejection("an image carrying a table no source provides",
                         lambda: inspect(orphan, version="9.9.9", build="1", tables=expected))

        empty = {"en.lproj": {}, "zh-Hans.lproj": tables["zh-Hans.lproj"]}
        silent = os.path.join(workspace, "empty-table.dmg")
        build_image(os.path.join(workspace, "staged-empty"), silent, with_link=True,
                    localizations=empty, info=prompt)
        expect_rejection("an image whose English table translates no prompt",
                         lambda: inspect(silent, version="9.9.9", build="1", tables=expected))

        none = os.path.join(workspace, "no-tables.dmg")
        build_image(os.path.join(workspace, "staged-none"), none, with_link=True, info=prompt)
        expect_rejection("an image with no prompt tables at all",
                         lambda: inspect(none, version="9.9.9", build="1", tables=expected))

        # Append a byte: both answers have to change, the image's and the sidecar's.
        with open(good, "ab") as handle:
            handle.write(b"appended by something between the runner and the release")
        expect_rejection("an image that fails its own checksum",
                         lambda: hdiutil_verify(good))
        expect_rejection("an image whose bytes changed after it was hashed",
                         lambda: verify_checksums([sidecar], [workspace]))
        print("self-test passed")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def self_test_checksums():
    """The ubuntu half of the rule: the sidecar binds the exact bytes, or it is worthless."""
    workspace = tempfile.mkdtemp(prefix="dmg-audit-sum-")
    try:
        image = os.path.join(workspace, "Moonlight-macOS-Enhanced-x86_64.dmg")
        with open(image, "wb") as handle:
            handle.write(b"\x00\x01\x02" * 1024)
        sidecar = write_checksum(image)
        verify_checksums([sidecar], [workspace])
        wanted = read_checksum([sidecar])[os.path.basename(image)]

        with open(image, "ab") as handle:
            handle.write(b"appended")
        try:
            verify_checksums([sidecar], [workspace])
        except SystemExit as failure:
            if wanted not in str(failure):
                raise AssertionError("the rejection did not name the hash that was expected: "
                                     "%s" % failure)
            print("rejects bytes that changed after they were hashed")
        else:
            raise AssertionError("accepted bytes that changed after they were hashed")

        # A sidecar that names a file nobody published must not pass quietly.
        with open(image, "wb") as handle:
            handle.write(b"\x00\x01\x02" * 1024)
        write_checksum(image)
        os.rename(image, image + ".renamed")
        expect_rejection("a checksum for a file that is not being published",
                         lambda: verify_checksums([sidecar], [workspace]))
        print("self-test passed")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("images", nargs="*", help="DMG files to check")
    parser.add_argument("--version", default=None, help="CFBundleShortVersionString expected")
    parser.add_argument("--build", default=None, help="CFBundleVersion expected")
    parser.add_argument("--write-checksums", action="store_true",
                        help="write <image>.sha256 beside each image that passes")
    parser.add_argument("--verify-checksums", nargs="+", metavar="SIDECAR",
                        help="compare the images being published against these files")
    parser.add_argument("--search", action="append", default=[],
                        help="directory to search for --verify-checksums (repeatable)")
    parser.add_argument("--skip-image-check", action="store_true",
                        help="hash only, for a host that cannot mount an HFS+ image")
    parser.add_argument("--localizations-from", default=SOURCE_LPROJ_ROOT,
                        metavar="DIR", help="directory whose <lang>.lproj tables the "
                                            "image has to carry (default: this repository's)")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--self-test-checksums", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return
    if args.self_test_checksums:
        self_test_checksums()
        return
    if args.verify_checksums:
        verify_checksums(args.verify_checksums, args.search or ["."])
        return
    if not args.images:
        parser.error("nothing to check; pass a DMG, --verify-checksums, or --self-test")
    for image in args.images:
        if not os.path.isfile(image):
            raise SystemExit("error: %s does not exist, so it was never packaged" % image)
        if not args.skip_image_check:
            hdiutil_verify(image)
            inspect(image, version=args.version, build=args.build,
                    tables=read_tables(args.localizations_from))
        if args.write_checksums:
            print("wrote %s" % write_checksum(image))


if __name__ == "__main__":
    main()
