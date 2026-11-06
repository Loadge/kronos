#!/usr/bin/env python
"""Run the screenshot tests in the CI image, from any machine with Docker.

    python bin/snapshots.py            compare with the baselines
    python bin/snapshots.py --update   replace them (then look at the new pictures in the diff)

The working tree goes into the container as a tar on stdin, and the pictures come back as a tar on
stdout, so nothing is mounted: the repo may live on a network drive Docker cannot share.
Differences land in .artifacts/snapshot_failures/. The image is tests/e2e/snapshots.Dockerfile, the
same base and install as the e2e job, and Docker caches it.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE = "kronos-snapshots"
TESTS = "tests/e2e/test_ui_snapshots.py tests/e2e/test_ui_a11y.py"
BACK = ["tests/e2e/__snapshots__", ".artifacts/snapshot_failures"]


def build_image() -> None:
    subprocess.run(
        ["docker", "build", "-q", "-t", IMAGE, "-f", "tests/e2e/snapshots.Dockerfile", "."],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )


def tree_as_tar() -> bytes:
    """Every tracked or new file of the working tree, without what git ignores."""
    listing = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tar:
        for name in listing.decode("utf-8").split("\0"):
            if name and (ROOT / name).is_file():
                tar.add(ROOT / name, arcname=name)
    return out.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update", action="store_true", help="replace the baselines")
    args = parser.parse_args()

    build_image()
    pytest = f"python -m pytest {TESTS} -q -n 4 -p no:cacheprovider"
    if args.update:
        pytest += " --update-snapshots"
    # pytest talks on stderr so that stdout carries only the tar coming back
    script = (
        f"tar x && mkdir -p {' '.join(BACK)} && {pytest} 1>&2; code=$?; "
        f"tar c {' '.join(BACK)}; exit $code"
    )
    done = subprocess.run(
        ["docker", "run", "--rm", "-i", IMAGE, "sh", "-c", script],
        input=tree_as_tar(),
        stdout=subprocess.PIPE,
    )
    with tarfile.open(fileobj=io.BytesIO(done.stdout)) as tar:
        tar.extractall(ROOT, filter="data")
    if args.update:
        # the plugin fails a test on purpose when it writes a picture; that is the job done here
        print("Baselines rewritten: review them with `git status` and the diff before committing.")
        return 0
    return done.returncode


if __name__ == "__main__":
    sys.exit(main())
