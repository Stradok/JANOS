"""Open the HUD without putting the login code on any command line.

`make janos-ui` runs this. It fetches a single-use login code with the API
token (kept in a file, never in argv), writes a tiny owner-only launcher page
that carries the code, and prints that file's path for xdg-open. The code
reaches the browser through a 0600 file, not through `ps`-visible arguments,
and it is spent the moment the page loads.

`--print-url MEM PORT` (used by the desktop app launcher, packaging/janos-app)
prints only the login URL to stdout and writes no launch.html. That URL is for
an app launcher that starts its browser with it as an argument; the code is
single-use and is spent on load.
"""

import os
import pathlib
import sys

import httpx


def build_url(code: str, port: str) -> str:
    return f"http://127.0.0.1:{port}/ui/#code={code}"


def main() -> int:
    args = sys.argv[1:]
    print_only = bool(args) and args[0] == "--print-url"
    if print_only:
        args = args[1:]
    mem, port = pathlib.Path(args[0]), args[1]
    token = (mem / "api_token").read_text(encoding="utf-8").strip()
    r = httpx.post(f"http://127.0.0.1:{port}/login-code",
                   headers={"Authorization": f"Bearer {token}"}, timeout=5)
    r.raise_for_status()
    code = r.json()["code"]
    url = build_url(code, port)
    if print_only:
        print(url)
        return 0
    launch = mem / "launch.html"
    page = ("<!doctype html><meta charset=utf-8><title>Opening JANOS</title>"
            f"<script>location.replace({url!r})</script>"
            "<body style='background:#05080d;color:#36d6ff;font-family:monospace'>Opening JANOS\u2026")
    # Create owner-only in one step; no readable window, no symlink follow.
    launch.unlink(missing_ok=True)
    fd = os.open(launch, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(launch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
