#!/usr/bin/env python3
"""Exercise CI failure propagation and mirroring with disposable Git repos."""

import base64
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CI = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text())
MIRROR = ROOT / "scripts/ci/publish-github.sh"


def run(*args, cwd=None, env=None, check=True):
    result = subprocess.run(args, cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=60)
    if check and result.returncode:
        raise AssertionError(result.stdout)
    return result


def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o700)


def selected(rules, context):
    # Deliberately support only the simple rules in this pipeline. A new
    # expression must extend the scenarios instead of silently passing.
    def value(term):
        if re.fullmatch(r"\$[A-Z_]+", term):
            return context.get(term[1:], "")
        if re.fullmatch(r'"[^"]*"', term):
            return term[1:-1]
        raise AssertionError("Unsupported CI expression: " + term)

    for rule in rules:
        condition = rule["if"].split(" == ")
        if len(condition) == 1:
            matches = bool(value(condition[0]))
        elif len(condition) == 2:
            matches = value(condition[0]) == value(condition[1])
        else:
            raise AssertionError("Unsupported CI rule: " + rule["if"])
        if matches:
            return rule.get("when") != "never"
    return False


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="moonlight-ci-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.home = self.root / "home"
        self.temp = self.root / "job temp"
        self.bin = self.root / "bin"
        for path in [self.home, self.temp, self.bin]:
            path.mkdir()
        # HOME is sandboxed only for these child processes.
        self.env = {
            **os.environ, "HOME": str(self.home), "TMPDIR": str(self.temp),
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "GIT_AUTHOR_NAME": "CI Fixture", "GIT_AUTHOR_EMAIL": "ci@example.invalid",
            "GIT_COMMITTER_NAME": "CI Fixture", "GIT_COMMITTER_EMAIL": "ci@example.invalid",
        }
        for key in list(self.env):
            if key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
                del self.env[key]
        self.env.pop("GIT_CONFIG_COUNT", None)

    def git(self, path, *args, check=True):
        return run("git", "-C", str(path), *args, env=self.env, check=check)


class PipelineTests(Sandbox):
    def test_event_matrix_and_stage_barrier(self):
        scenarios = [
            ("push", "main", "", True, True, True),
            ("push", "feature/example", "", True, False, True),
            ("push", "", "v1.2.3", True, True, True),
            ("web", "main", "", True, True, True),
            ("web", "feature/example", "", True, False, True),
            ("web", "", "v1.2.3", True, True, True),
            ("merge_request_event", "", "", True, False, False),
            ("schedule", "main", "", False, False, False),
            ("api", "", "v1.2.3", False, False, False),
        ]
        gates = ["lint:toolchain", "audit:python", "download-deps",
                 "build-app", "test-app", "audit:sources"]
        for source, branch, tag, workflow, package, mirror in scenarios:
            with self.subTest(source=source, branch=branch, tag=tag):
                context = {"CI_PIPELINE_SOURCE": source, "CI_COMMIT_BRANCH": branch,
                           "CI_COMMIT_TAG": tag, "CI_DEFAULT_BRANCH": "main"}
                enabled = selected(CI["workflow"]["rules"], context)
                self.assertEqual(enabled, workflow)
                for gate in gates:
                    self.assertEqual(enabled and selected(CI[gate]["rules"], context), workflow)
                self.assertEqual(enabled and selected(CI["package-dmg"]["rules"], context), package)
                self.assertEqual(enabled and selected(CI["publish-github"]["rules"], context), mirror)
                # The battery covers the same events as the DMG gate.
                self.assertEqual(enabled and selected(CI["mutation-battery"]["rules"], context), package)
        publisher = CI["publish-github"]
        self.assertGreater(CI["stages"].index(publisher["stage"]),
                           CI["stages"].index(CI["package-dmg"]["stage"]))
        self.assertNotIn("needs", publisher, "DAG needs must not bypass the stage barrier")
        self.assertEqual(publisher["resource_group"], "github-mirror")
        self.assertFalse(publisher["interruptible"])
        self.assertEqual(publisher["tags"], ["gitlab-mirror"])
        self.assertEqual(publisher["script"], [
            "MIRROR_DRY_RUN=1 python3 scripts/ci/publish-github.py",
            "python3 scripts/ci/publish-github.py"])
        for name in gates + ["package-dmg", "publish-github"]:
            self.assertIn("timeout", CI[name])
            self.assertFalse(CI[name].get("allow_failure", False))
        self.assertNotIn("cache", CI)

    def test_battery_runs_after_the_release_path(self):
        # Pipeline 647: the battery shared the test stage with the release path
        # on one 8-core runner and starved audit:python into its timeout, which
        # skipped every downstream gate and left main without a DMG. The
        # structural guarantee against that regression is the stage order plus
        # the absence of a needs: shortcut, so both are pinned here.
        battery = CI["mutation-battery"]
        for name, job in CI.items():
            if isinstance(job, dict) and "stage" in job:
                self.assertIn(job["stage"], CI["stages"], f"{name} declares an unknown stage")
        stages = CI["stages"]
        self.assertGreater(stages.index(battery["stage"]),
                           stages.index(CI["package-dmg"]["stage"]),
                           "the battery must not compete with the release path")
        self.assertLess(stages.index(battery["stage"]),
                        stages.index(CI["publish-github"]["stage"]),
                        "a red battery must still hold the mirror back")
        self.assertNotIn("needs", battery,
                         "needs: would let the battery start beside the release path")
        self.assertEqual(battery["resource_group"], "macos-battery",
                         "two batteries must not share the runner at once")
        self.assertIn("timeout", battery)
        self.assertFalse(battery.get("allow_failure", False),
                         "a skipped battery silently stops gating")

    def job(self, name):
        return run("bash", "-c", "\n".join(CI[name]["script"]),
                   cwd=self.root, env=self.env, check=False)

    def build_fixture(self, code=0, version_code=0):
        executable(self.root / "Limelight/build-number.sh",
                   "#!/bin/sh\nprintf '123\\n'\nexit %d\n" % version_code)
        executable(self.bin / "xcodebuild",
                   '#!/bin/sh\nprintf "%%s\\n" "$@" > build-arguments\nexit %d\n' % code)
        executable(self.bin / "xcpretty", "#!/bin/sh\ncat\n")
        self.env.update(XCODE_PROJECT="Fixture.xcodeproj", XCODE_SCHEME="Fixture",
                        CONFIGURATION="Release", DERIVED_DATA_PATH="build/derivedData")

    def test_failed_build_survives_tee_and_formatter(self):
        self.build_fixture(code=42)
        self.assertEqual(self.job("build-app").returncode, 42)
        self.assertEqual((self.root / "build-arguments").read_text().splitlines()[-2:],
                         ["clean", "build"])

    def test_successful_build_passes(self):
        self.build_fixture()
        self.assertEqual(self.job("build-app").returncode, 0)

    def test_build_number_failure_stops_before_build(self):
        self.build_fixture(version_code=19)
        self.assertEqual(self.job("build-app").returncode, 19)
        self.assertFalse((self.root / "build-arguments").exists())

    def test_failed_smoke_survives_tee(self):
        executable(self.root / "scripts/integration-test.sh", "#!/bin/sh\nexit 31\n")
        self.env.update(CONFIGURATION="Release", DERIVED_DATA_PATH="build/derivedData")
        self.assertEqual(self.job("test-app").returncode, 31)

    def test_submodule_auth_is_runtime_only_and_preserves_runner_config(self):
        executable(self.bin / "git", "#!" + sys.executable + "\n"
                   "import json, os\n"
                   "with open(os.environ['CAPTURE'], 'a') as stream:\n"
                   "    stream.write(json.dumps({k:v for k,v in os.environ.items() "
                   "if k.startswith('GIT_CONFIG_')}) + '\\n')\n")
        capture = self.root / "git-env"
        self.env.update(GRP_CI_JOB_TOKEN="fixture-value",
                        GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.autocrlf",
                        GIT_CONFIG_VALUE_0="false", CAPTURE=str(capture))
        run("bash", str(ROOT / "scripts/ci/fetch-submodules.sh"), env=self.env)
        entries = [json.loads(line) for line in capture.read_text().splitlines()]
        self.assertEqual(len(entries), 2)
        for entry in entries:
            self.assertEqual(entry["GIT_CONFIG_COUNT"], "2")
            self.assertEqual(entry["GIT_CONFIG_VALUE_0"], "false")
            self.assertEqual(entry["GIT_CONFIG_KEY_1"],
                             "http.http://172.16.130.6/moonlight/moonlight-common-c.git.extraHeader")
            self.assertEqual(entry["GIT_CONFIG_VALUE_1"], "Authorization: Basic " +
                             base64.b64encode(b"oauth2:fixture-value").decode())
        self.assertFalse((self.home / ".gitconfig").exists())


class MirrorTests(Sandbox):
    def setUp(self):
        super().setUp()
        self.source = self.root / "source.git"
        self.target = self.root / "target.git"
        self.work = self.root / "work"
        for bare in [self.source, self.target]:
            run("git", "init", "--bare", "--quiet", str(bare), env=self.env)
        self.work.mkdir()
        self.git(self.work, "init", "--quiet")
        self.git(self.work, "checkout", "-b", "main")
        self.git(self.work, "commit", "--allow-empty", "-m", "first")
        self.first = self.git(self.work, "rev-parse", "HEAD").stdout.strip()
        self.git(self.work, "branch", "feature/example")
        self.git(self.work, "tag", "-a", "release-one", "-m", "annotated tag")
        self.git(self.work, "push", str(self.source), "--all")
        self.git(self.work, "push", str(self.source), "--tags")
        key = self.root / "fixture-key"
        key.write_text("fixture only; local Git transport does not authenticate\n")
        (self.home / ".ssh").mkdir()
        for name in ["config", "known_hosts", "gh_deploy"]:
            (self.home / ".ssh" / name).write_text("untouched " + name)
        self.env.update(GH_DEPLOY_KEY=str(key), CI_REPOSITORY_URL=str(self.source),
                        CI_COMMIT_REF_NAME="main", CI_COMMIT_SHA=self.first,
                        CI_COMMIT_TAG="", GITHUB_MIRROR_URL=str(self.target))

    def refs(self, repo):
        return self.git(repo, "for-each-ref", "--format=%(objectname) %(refname)",
                        "refs/heads", "refs/tags").stdout

    def mirror(self, success=True):
        result = run("bash", str(MIRROR), env=self.env, check=False)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(list(self.temp.iterdir()), [], "temporary credentials must be removed")
        for name in ["config", "known_hosts", "gh_deploy"]:
            self.assertEqual((self.home / ".ssh" / name).read_text(), "untouched " + name)
        self.assertFalse((self.home / ".gitconfig").exists())
        return result

    def advance(self):
        self.git(self.work, "commit", "--allow-empty", "-m", "second")
        sha = self.git(self.work, "rev-parse", "HEAD").stdout.strip()
        self.git(self.work, "push", str(self.source), "main")
        return sha

    def test_mirrors_all_branches_and_annotated_tags_and_prunes_both(self):
        self.git(self.work, "push", str(self.target), "main:refs/heads/obsolete",
                 "HEAD:refs/tags/obsolete")
        self.mirror()
        self.assertEqual(self.refs(self.source), self.refs(self.target))
        self.git(self.source, "update-ref", "-d", "refs/heads/feature/example")
        self.git(self.source, "update-ref", "-d", "refs/tags/release-one")
        self.mirror()
        self.assertEqual(self.refs(self.source), self.refs(self.target))

    def test_annotated_tag_pipeline_uses_peeled_commit(self):
        self.env.update(CI_COMMIT_REF_NAME="release-one", CI_COMMIT_TAG="release-one")
        self.mirror()
        self.assertEqual(self.refs(self.source), self.refs(self.target))

    def test_retry_of_old_pipeline_cannot_overwrite_new_mirror(self):
        self.mirror()
        self.env["CI_COMMIT_SHA"] = self.advance()
        self.mirror()
        expected = self.refs(self.target)
        self.env["CI_COMMIT_SHA"] = self.first
        self.assertIn("superseded", self.mirror().stdout)
        self.assertEqual(self.refs(self.target), expected)

    def test_deleted_trigger_skips(self):
        self.mirror()
        before = self.refs(self.target)
        self.env.update(CI_COMMIT_REF_NAME="feature/example")
        self.git(self.source, "update-ref", "-d", "refs/heads/feature/example")
        self.assertIn("superseded", self.mirror().stdout)
        self.assertEqual(self.refs(self.target), before)

    def test_failed_fetch_and_empty_source_leave_target_intact(self):
        self.mirror()
        before = self.refs(self.target)
        self.env["CI_REPOSITORY_URL"] = str(self.root / "missing.git")
        self.mirror(success=False)
        self.assertEqual(self.refs(self.target), before)
        empty = self.root / "empty.git"
        run("git", "init", "--bare", "--quiet", str(empty), env=self.env)
        self.env["CI_REPOSITORY_URL"] = str(empty)
        self.assertIn("no branches", self.mirror(success=False).stdout)
        self.assertEqual(self.refs(self.target), before)

    def test_rejected_tag_does_not_partially_update_branches(self):
        self.mirror()
        before = self.refs(self.target)
        self.env["CI_COMMIT_SHA"] = self.advance()
        self.git(self.work, "tag", "blocked")
        self.git(self.work, "push", str(self.source), "refs/tags/blocked")
        executable(self.target / "hooks/update",
                   '#!/bin/sh\n[ "$1" != refs/tags/blocked ]\n')
        self.mirror(success=False)
        self.assertEqual(self.refs(self.target), before)

    def test_ssh_options_are_isolated_and_host_verification_is_strict(self):
        # Route the Git protocol to the fixture but let real OpenSSH resolve
        # the generated config. No network access or private key is required.
        capture = self.root / "ssh-options"
        executable(self.bin / "ssh", "#!" + sys.executable + "\n"
                   "import os, subprocess, sys\n"
                   "config = sys.argv[sys.argv.index('-F') + 1]\n"
                   "with open(os.environ['SSH_CAPTURE'], 'w') as stream:\n"
                   "    subprocess.run(['/usr/bin/ssh', '-G', '-F', config, 'github.com'], "
                   "stdout=stream, check=True)\n"
                   "command = sys.argv[-1].split()[0]\n"
                   "assert command in ('git-receive-pack', 'git-upload-pack')\n"
                   "os.execvp(command, [command, os.environ['FIXTURE_TARGET']])\n")
        self.env.update(GITHUB_MIRROR_URL="git@github.com:opsbsligm/moonlight-macos-enhanced.git",
                        SSH_CAPTURE=str(capture), FIXTURE_TARGET=str(self.target))
        self.mirror()
        options = dict(line.split(" ", 1) for line in capture.read_text().splitlines()
                       if " " in line)
        self.assertEqual(options["stricthostkeychecking"], "true")
        self.assertEqual(options["identitiesonly"], "yes")
        self.assertEqual(options["identityagent"], "none")
        self.assertEqual(options["batchmode"], "yes")
        self.assertEqual(options["globalknownhostsfile"], "/dev/null")
        self.assertIn(str(self.temp), options["identityfile"])
        self.assertIn(str(self.temp), options["userknownhostsfile"])
        self.assertEqual(self.refs(self.source), self.refs(self.target))


@unittest.skipUnless(sys.platform == "darwin", "launch fixture needs macOS codesign")
class LaunchTests(Sandbox):
    def test_existing_instance_cannot_mask_a_failed_launch_and_is_not_killed(self):
        app = self.root / "MoonlightEnhanced.app"
        contents = app / "Contents"
        for folder in ["MacOS", "Resources", "Frameworks"]:
            (contents / folder).mkdir(parents=True)
        with (contents / "Info.plist").open("wb") as stream:
            plistlib.dump({"CFBundleIdentifier": "test.moonlight.ci",
                          "CFBundleShortVersionString": "1.0",
                          "CFBundleExecutable": "SmokeFixture",
                          "LSMinimumSystemVersion": "12.0"}, stream)
        source = self.root / "smoke.c"
        source.write_text('#include <stdlib.h>\n#include <unistd.h>\n'
                          'int main(void) { if (getenv("SMOKE_EXIT")) return 17; '
                          'sleep(45); return 0; }\n')
        binary = contents / "MacOS/SmokeFixture"
        run("xcrun", "clang", str(source), "-o", str(binary))
        run("codesign", "--force", "--sign", "-", str(app))
        (self.home / "Library/Logs/DiagnosticReports").mkdir(parents=True)
        existing = subprocess.Popen([str(binary)], env=self.env)
        def stop():
            if existing.poll() is None:
                existing.terminate()
            existing.wait(timeout=5)
        self.addCleanup(stop)
        for fail in [False, True]:
            env = dict(self.env)
            if fail:
                env["SMOKE_EXIT"] = "1"
            result = run("bash", str(ROOT / "scripts/integration-test.sh"), str(app),
                         env=env, check=False)
            self.assertEqual(result.returncode == 0, not fail, result.stdout)
            self.assertIsNone(existing.poll(), "the user's existing instance must survive")
        self.assertEqual(list(self.temp.iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
