"""Run the conservative ALDI TALK +1 GB check in a headless cloud browser."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from portal_reader import PORTAL_URL, is_portal_host, parse_portal_text


REFILL_LABEL = re.compile(r"^\s*\+\s*1\s*GB\s*$", re.I)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_last_attempt(path: Path) -> datetime | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = datetime.fromisoformat(payload["last_attempt_at"])
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def in_cooldown(last_attempt: datetime | None, now: datetime, minutes: int) -> bool:
    return bool(last_attempt and now - last_attempt < timedelta(minutes=minutes))


def decide_action(
    remaining_mb: int | None,
    threshold_mb: int,
    control_status: str,
    execute: bool,
    cooling_down: bool,
) -> str:
    if remaining_mb is None:
        return "UNVERIFIED"
    if remaining_mb > threshold_mb:
        return "MONITORING"
    if control_status != "ENABLED":
        return "WAITING_FOR_REFILL_CONTROL"
    if cooling_down:
        return "COOLDOWN"
    return "BOOK" if execute else "READY_TO_BOOK"


def save_attempt(path: Path, status: str, attempted_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"last_attempt_at": attempted_at.isoformat(), "status": status}),
        encoding="utf-8",
    )
    temporary.replace(path)


def refill_target(page):
    """Require exactly one visible and clickable control named '+1 GB'."""
    labels = page.get_by_text(REFILL_LABEL, exact=True)
    visible = []
    for index in range(min(labels.count(), 20)):
        label = labels.nth(index)
        if label.is_visible():
            visible.append(label)
    if len(visible) != 1:
        return None, "UNKNOWN"

    label = visible[0]
    semantic = label.locator(
        "xpath=ancestor-or-self::button | ancestor-or-self::a | "
        "ancestor-or-self::*[@role='button'] | "
        "ancestor-or-self::input[@type='button'] | "
        "ancestor-or-self::input[@type='submit']"
    )
    target = semantic.first if semantic.count() else label
    if not target.is_visible() or not target.is_enabled():
        return target, "DISABLED"
    try:
        target.click(trial=True, timeout=3000)
    except Exception:
        return target, "UNKNOWN"
    return target, "ENABLED"


def wait_for_increase(page, previous_mb: int, timeout_seconds: int = 30) -> int | None:
    for _ in range(timeout_seconds):
        page.wait_for_timeout(1000)
        reading = parse_portal_text(page.locator("body").inner_text(timeout=15000))
        if reading.remaining_mb is not None and reading.remaining_mb > previous_mb:
            return reading.remaining_mb
    return None


def at_stage(code: str, operation):
    try:
        return operation()
    except Exception as exc:
        raise RuntimeError(f"{code}_{type(exc).__name__.upper()}") from exc


def navigate_to_portal(page) -> None:
    """Open the overview directly and tolerate short-lived portal timeouts."""
    last_error = None
    for attempt in range(3):
        try:
            page.goto(PORTAL_URL, wait_until="commit", timeout=45000)
            page.wait_for_timeout(1500)
            return
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                page.wait_for_timeout(3000)
    raise last_error


def wait_for_reading(page, timeout_seconds: int = 30):
    """Wait until the domestic allowance can be parsed without naming a plan."""
    for _ in range(timeout_seconds):
        reading = parse_portal_text(page.locator("body").inner_text(timeout=15000))
        if reading.remaining_mb is not None:
            return reading
        page.wait_for_timeout(1000)
    raise RuntimeError("PORTAL_DATA_NOT_READY")


def run_live(
    storage_state: Path,
    state_file: Path,
    threshold_mb: int,
    cooldown_minutes: int,
    execute: bool,
    wait_seconds: int,
) -> dict:
    from playwright.sync_api import sync_playwright

    now = utc_now()
    with sync_playwright() as playwright:
        browser = at_stage(
            "STAGE_BROWSER_START",
            lambda: playwright.chromium.launch(headless=True),
        )
        context = at_stage(
            "STAGE_SESSION_LOAD",
            lambda: browser.new_context(
                storage_state=str(storage_state),
                accept_downloads=False,
                locale="de-DE",
            ),
        )
        try:
            page = context.new_page()
            at_stage(
                "STAGE_PORTAL_LOAD",
                lambda: navigate_to_portal(page),
            )
            at_stage(
                "STAGE_BALANCE_WAIT",
                lambda: page.get_by_text("Dein Guthaben", exact=False).first.wait_for(
                    timeout=wait_seconds * 1000
                ),
            )
            if not is_portal_host(page.url):
                raise RuntimeError("PORTAL_DOMAIN_UNERWARTET")

            reading = at_stage(
                "STAGE_DATA_WAIT",
                lambda: wait_for_reading(page),
            )
            target, control_status = refill_target(page)
            action = decide_action(
                reading.remaining_mb,
                threshold_mb,
                control_status,
                execute,
                in_cooldown(load_last_attempt(state_file), now, cooldown_minutes),
            )
            result = {
                "status": action,
                "booking_clicked": False,
                "booking_confirmed": False,
            }
            if action != "BOOK":
                return result

            if not is_portal_host(page.url):
                raise RuntimeError("PORTAL_DOMAIN_UNERWARTET")
            fresh = parse_portal_text(page.locator("body").inner_text(timeout=15000))
            target, control_status = refill_target(page)
            if (
                fresh.remaining_mb is None
                or fresh.remaining_mb > threshold_mb
                or target is None
                or control_status != "ENABLED"
            ):
                return {
                    "status": "CONDITIONS_CHANGED",
                    "booking_clicked": False,
                    "booking_confirmed": False,
                }

            save_attempt(state_file, "REQUESTED", now)
            target.click(timeout=10000)
            result["booking_clicked"] = True
            increased = wait_for_increase(page, fresh.remaining_mb)
            if increased is not None:
                result["status"] = "CONFIRMED"
                result["booking_confirmed"] = True
                save_attempt(state_file, "CONFIRMED", now)
            else:
                result["status"] = "CLICKED_UNCONFIRMED"
                save_attempt(state_file, "CLICKED_UNCONFIRMED", now)
            return result
        finally:
            context.close()
            browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="ALDI AutoRefill for GitHub Actions")
    parser.add_argument("--storage-state", type=Path, required=True)
    parser.add_argument("--state-file", type=Path, default=Path(".state/attempt.json"))
    parser.add_argument("--threshold-mb", type=int, required=True)
    parser.add_argument("--cooldown-minutes", type=int, default=30)
    parser.add_argument("--wait-seconds", type=int, default=90)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    try:
        if not args.storage_state.is_file():
            raise RuntimeError("SESSION_SECRET_FEHLT")
        if not 1 <= args.threshold_mb <= 10000:
            raise ValueError("ungueltiger Schwellenwert")
        if not 1 <= args.cooldown_minutes <= 1440:
            raise ValueError("ungueltige Sperrzeit")
        result = run_live(
            args.storage_state,
            args.state_file,
            args.threshold_mb,
            args.cooldown_minutes,
            args.execute,
            args.wait_seconds,
        )
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        runtime_code = str(exc) if isinstance(exc, RuntimeError) else ""
        error_code = runtime_code if (
            runtime_code in {"PORTAL_DOMAIN_UNERWARTET", "SESSION_SECRET_FEHLT"}
            or runtime_code.startswith("STAGE_")
        ) else "NICHT_KLASSIFIZIERT"
        print(json.dumps({"status": "ERROR", "error_code": error_code}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
