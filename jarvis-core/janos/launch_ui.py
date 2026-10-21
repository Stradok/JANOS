"""Open the HUD without putting the login code on any command line.

`make janos-ui` runs this. It fetches a single-use login code with the API
token (kept in a file, never in argv), writes a tiny owner-only launcher page
that carries the code, and prints that file's path for xdg-open. The code
reaches the browser through a 0600 file, not through `ps`-visible arguments,
and it is spent the moment the page loads.
"""

import pathlib
import sys

import httpx


def main() -> int:
    mem, port = pathlib.Path(sys.argv[1]), sys.argv[2]
    token = (mem / "api_token").read_text(encoding="utf-8").strip()
    r = httpx.post(f"http://127.0.0.1:{port}/login-code",
                   headers={"Authorization": f"Bearer {token}"}, timeout=5)
    r.raise_for_status()
    code = r.json()["code"]
    url = f"http://127.0.0.1:{port}/ui/#code={code}"
    launch = mem / "launch.html"
    launch.write_text(
        "<!doctype html><meta charset=utf-8><title>Opening JANOS</title>"
        f"<script>location.replace({url!r})</script>"
        "<body style='background:#05080d;color:#36d6ff;font-family:monospace'>Opening JANOS…",
        encoding="utf-8")
    launch.chmod(0o600)
    print(launch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
