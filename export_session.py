"""Export the existing local ALDI login into a GitHub-ready Playwright state."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from portal_reader import PORTAL_URL, is_portal_host


def main() -> None:
    parser = argparse.ArgumentParser(description="ALDI-Sitzung sicher exportieren")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(args.profile),
            headless=args.headless,
            accept_downloads=False,
            locale="de-DE",
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(PORTAL_URL, wait_until="commit", timeout=45000)
            page.get_by_text("Dein Guthaben", exact=False).first.wait_for(timeout=120000)
            if not is_portal_host(page.url):
                raise RuntimeError("PORTAL_DOMAIN_UNERWARTET")
            context.storage_state(path=str(args.output), indexed_db=True)
        finally:
            context.close()

    os.chmod(args.output, 0o600)
    payload = json.loads(args.output.read_text(encoding="utf-8"))
    if not payload.get("cookies") and not payload.get("origins"):
        args.output.unlink(missing_ok=True)
        raise RuntimeError("LEERE_SITZUNG")
    print(json.dumps({"status": "SESSION_EXPORTED", "contains_login_data": True}))


if __name__ == "__main__":
    main()
