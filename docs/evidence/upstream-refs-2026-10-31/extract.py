#!/usr/bin/env python3
"""Deterministic projection of the upstream API responses this snapshot ships.

The raw responses are dropped on purpose: the Sunshine releases payload carries 800 KB
of changelog text and nothing in the matrix depends on it. A projection is only
evidence if anyone can rebuild it, so the command that rebuilds every file here is
recorded in README.md and this script is the single source of its shape -- rerun it and
compare byte for byte, or the snapshot has drifted from the document that pins it.

Usage: extract.py <raw-json-file> <projection-name>
"""
import json
import sys


def project(raw, name):
    doc = json.load(raw)
    if name == "sunshine-releases.json":
        return [{"tag_name": r.get("tag_name"), "prerelease": r.get("prerelease"),
                 "published_at": r.get("published_at"),
                 "target_commitish": r.get("target_commitish")} for r in doc]
    if name.endswith("-commit.json") or "-master.json" in name:
        commit = doc.get("commit") or {}
        committer = commit.get("committer") or {}
        return {"sha": doc.get("sha"),
                "date": committer.get("date"),
                "message_head": (commit.get("message") or doc.get("message") or "").splitlines()[0]}
    if name.endswith("-tag-v6.2.0.json"):
        return {"ref": doc.get("ref"), "object": doc.get("object")}
    if name.endswith("-tag-v2026.1018.5342.json"):
        return {"status": doc.get("status"), "message": doc.get("message")}
    raise SystemExit("no projection for %s" % name)


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as handle:
        text = json.dumps(project(handle, sys.argv[2]), indent=2, ensure_ascii=False,
                          sort_keys=True) + "\n"
    sys.stdout.write(text)
