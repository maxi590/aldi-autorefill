"""Run the conservative ALDI TALK +1 GB check in a headless cloud browser."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from portal_reader import (
    PORTAL_URL,
    is_portal_host,
    parse_portal_readings,
    parse_portal_text,
)


REFILL_LABEL = re.compile(r"^\s*\+\s*1\s*GB\s*$", re.I)
BARE_REFILL_LABEL = re.compile(r"^\s*1\s*GB\s*$", re.I)
ONE_GB_LABEL = re.compile(r"\b1\s*GB\b", re.I)
REFILL_WORD = re.compile(r"nachbuch|kostenlos|weiteres|zus[aä]tzlich", re.I)


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
    # A unique enabled refill control is authoritative when the numeric card
    # lags behind ALDI's eligibility state.
    if remaining_mb >= threshold_mb and control_status != "ENABLED":
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


def balance_band(remaining_mb: int | None, threshold_mb: int) -> str:
    """Return a privacy-safe threshold relation without logging the balance."""
    if remaining_mb is None:
        return "UNKNOWN"
    if remaining_mb < threshold_mb:
        return "BELOW_THRESHOLD"
    if remaining_mb == threshold_mb:
        return "AT_THRESHOLD"
    return "ABOVE_THRESHOLD"


def refill_page_signals(page) -> dict[str, bool]:
    """Report only generic refill words, never account or allowance text."""
    body = page.locator("body").inner_text(timeout=15000)
    return {
        "one_gb_text_present": bool(ONE_GB_LABEL.search(body)),
        "plus_one_gb_text_present": bool(re.search(r"\+\s*1\s*GB", body, re.I)),
        "refill_word_present": bool(REFILL_WORD.search(body)),
    }


def reading_band_counts(page, threshold_mb: int) -> dict[str, int]:
    """Count domestic cards by band without exposing allowance values."""
    body = page.locator("body").inner_text(timeout=15000)
    readings = parse_portal_readings(body)
    return {
        "domestic_reading_count": len(readings),
        "below_threshold_readings": sum(
            reading.remaining_mb is not None
            and reading.remaining_mb < threshold_mb
            for reading in readings
        ),
    }


def refill_dom_diagnostics(page) -> dict[str, list[dict]]:
    """Describe only generic DOM properties around the refill label."""
    labels = page.get_by_text(ONE_GB_LABEL, exact=False)
    for index in range(min(labels.count(), 20)):
        label = labels.nth(index)
        if not label.is_visible() or not is_refill_label(label.inner_text(timeout=3000)):
            continue
        chain = label.evaluate(
            """element => {
                const result = [];
                let current = element;
                for (let depth = 0; current && depth <= 8; depth += 1) {
                    const style = getComputedStyle(current);
                    const classes = String(current.className || '')
                        .split(/\s+/)
                        .filter(value => /^[A-Za-z0-9_-]{1,60}$/.test(value))
                        .slice(0, 6);
                    result.push({
                        depth,
                        tag: current.tagName.toLowerCase(),
                        role: current.getAttribute('role') || '',
                        cursor: style.cursor,
                        pointer_events: style.pointerEvents,
                        tabindex: current.getAttribute('tabindex') || '',
                        has_onclick: current.hasAttribute('onclick'),
                        classes,
                    });
                    current = current.parentElement;
                }
                return result;
            }"""
        )
        return {"refill_ancestor_chain": chain}
    return {"refill_ancestor_chain": []}


def is_refill_label(text: str) -> bool:
    """Recognize the short labels ALDI uses for the free refill control."""
    normalized = re.sub(r"\s+", " ", text).strip()
    return bool(
        REFILL_LABEL.fullmatch(normalized)
        or BARE_REFILL_LABEL.fullmatch(normalized)
        or (ONE_GB_LABEL.search(normalized) and REFILL_WORD.search(normalized))
    )


def clickable_refill_ancestor(label, max_depth: int = 6):
    """Find ALDI's click-card wrapper when it is not a semantic button."""
    element = label.element_handle()
    for _ in range(max_depth + 1):
        if element is None:
            break
        clickish = element.evaluate(
            """element => {
                const tag = element.tagName.toLowerCase();
                const role = (element.getAttribute('role') || '').toLowerCase();
                const tabindex = element.getAttribute('tabindex');
                const cursor = getComputedStyle(element).cursor;
                return tag === 'button' || tag === 'a' || tag === 'one-button' ||
                    role === 'button' ||
                    element.hasAttribute('onclick') || tabindex === '0' ||
                    cursor === 'pointer';
            }"""
        )
        if clickish and element.is_visible() and element.is_enabled():
            try:
                element.click(trial=True, timeout=500)
                return element
            except Exception:
                pass
        parent = element.evaluate_handle("element => element.parentElement")
        element = parent.as_element()
    return None


def refill_target(page):
    """Find one visible domestic 1 GB refill control without exposing page text."""
    labels = page.get_by_text(ONE_GB_LABEL, exact=False)
    visible = []
    for index in range(min(labels.count(), 20)):
        label = labels.nth(index)
        if not label.is_visible():
            continue
        text = label.inner_text(timeout=3000)
        if is_refill_label(text):
            visible.append(label)

    candidates = []
    for label in visible:
        semantic = label.locator(
            "xpath=ancestor-or-self::*["
            "self::button or self::a or @role='button' or "
            "(self::input and (@type='button' or @type='submit'))"
            "][1]"
        )
        target = semantic.first if semantic.count() else clickable_refill_ancestor(label)
        if target is None:
            continue

        domestic_context = label.locator(
            "xpath=ancestor::*["
            "contains(translate(normalize-space(.), 'INLAND', 'inland'), 'inland')"
            "][1]"
        )
        is_domestic = bool(domestic_context.count())
        candidates.append((target, is_domestic))

    domestic = [target for target, is_domestic in candidates if is_domestic]
    if len(domestic) == 1:
        return domestic[0], "ENABLED", len(visible), len(candidates)
    if len(candidates) == 1:
        return candidates[0][0], "ENABLED", len(visible), len(candidates)
    if len(candidates) > 1:
        return None, "AMBIGUOUS", len(visible), len(candidates)
    if visible:
        return None, "BLOCKED", len(visible), 0
    return None, "MISSING", 0, 0


def wait_for_refill_target(page, timeout_seconds: int = 8):
    """Allow the refill control to load after the allowance reading appears."""
    last = (None, "MISSING", 0, 0)
    for _ in range(timeout_seconds):
        last = refill_target(page)
        if last[1] == "ENABLED":
            return last
        page.wait_for_timeout(1000)
    return last


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
                viewport={"width": 430, "height": 932},
                screen={"width": 430, "height": 932},
                device_scale_factor=1,
                is_mobile=True,
                has_touch=True,
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
            if reading.remaining_mb <= threshold_mb:
                target, control_status, visible_labels, clickable_controls = (
                    wait_for_refill_target(page)
                )
            else:
                target, control_status, visible_labels, clickable_controls = (
                    refill_target(page)
                )
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
                "balance_band": balance_band(reading.remaining_mb, threshold_mb),
                "control_status": control_status,
                "visible_refill_labels": visible_labels,
                "clickable_refill_controls": clickable_controls,
                **refill_page_signals(page),
                **reading_band_counts(page, threshold_mb),
                **refill_dom_diagnostics(page),
            }
            if action != "BOOK":
                return result

            if not is_portal_host(page.url):
                raise RuntimeError("PORTAL_DOMAIN_UNERWARTET")
            fresh = parse_portal_text(page.locator("body").inner_text(timeout=15000))
            target, control_status, _, _ = wait_for_refill_target(page, 5)
            if (
                fresh.remaining_mb is None
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
