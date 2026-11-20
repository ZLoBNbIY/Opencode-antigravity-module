"""Allocate stable Windows release versions from Git tags."""

import re
import subprocess


BASE_VERSION = (2, 0, 0)
VERSION_TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def stable_tags(tags):
    for tag in tags:
        match = VERSION_TAG.fullmatch(tag)
        if match:
            yield tuple(map(int, match.groups()))


def release_tag(all_tags, current_tags):
    current = list(stable_tags(current_tags))
    if current:
        version = max(current)
        existing = True
    else:
        major, minor, patch = max(BASE_VERSION, max(stable_tags(all_tags), default=BASE_VERSION))
        version = (major, minor, patch + 1)
        existing = False
    if max(version) > 65535:
        raise ValueError("Windows file version components must be at most 65535; an explicit version baseline is required")
    return "v" + ".".join(map(str, version)), existing


def git_tags(*args):
    return subprocess.check_output(["git", "tag", "--list", *args], text=True).splitlines()


if __name__ == "__main__":
    tag, _ = release_tag(git_tags(), git_tags("--points-at", "HEAD"))
    print(tag)
