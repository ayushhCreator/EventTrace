from __future__ import annotations

import argparse
import re
import time
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_coin_name(raw: str) -> str:
    text = " ".join(raw.replace("\n", " ").split()).strip()
    if text.lower().endswith(" buy"):
        text = text[: -len(" buy")].strip()
    parts = text.split()
    if len(parts) >= 2 and parts[-1].isupper() and 2 <= len(parts[-1]) <= 10:
        # Drop ticker/suffix like BTC, ETH, CMC20
        parts = parts[:-1]
    return " ".join(parts).strip()


_PRICE_RE = re.compile(r"[^0-9.\-]+")


def _clean_price(raw: str) -> str | None:
    text = " ".join(raw.replace("\n", " ").split()).strip()
    if text in {"", "-", "—"}:
        return None
    # "$76,176.31" -> "76176.31"
    cleaned = _PRICE_RE.sub("", text)
    return cleaned if cleaned != "" else None


def scrape_coinmarketcap_name_price(*, headless: bool = True, chromium_sandbox: bool = False) -> dict[str, str]:
    url = "https://coinmarketcap.com/"
    table_selector = "table.cmc-table"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, chromium_sandbox=chromium_sandbox)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        page.wait_for_selector(table_selector, timeout=60_000)

        table = page.locator(table_selector).first
        headers = [h.inner_text().strip() for h in table.locator("thead tr").first.locator("th").all()]
        headers = [" ".join(h.split()) for h in headers]

        def col_idx(name: str) -> int:
            try:
                return headers.index(name)
            except ValueError as e:
                raise RuntimeError(f"Missing column {name!r}. Found headers={headers!r}") from e

        name_i = col_idx("Name")
        price_i = col_idx("Price")

        out: dict[str, str] = {}
        for tr in table.locator("tbody tr").all():
            cells = tr.locator("th,td").all()
            if len(cells) <= max(name_i, price_i):
                continue
            name_raw = cells[name_i].inner_text()
            price_raw = cells[price_i].inner_text()
            name = _clean_coin_name(name_raw)
            price = _clean_price(price_raw)
            if name and price:
                out[name] = price

        context.close()
        browser.close()
        return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple CoinMarketCap Name->Price tracker (5 min default).")
    parser.add_argument("--minutes", type=int, default=5)
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--chromium-sandbox", action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args()

    end_at = time.time() + (args.minutes * 60)
    prev: dict[str, str] | None = None

    print(f"[{_utc_now_iso()}] tracking CoinMarketCap name+price for {args.minutes} min")

    while time.time() < end_at:
        snap = scrape_coinmarketcap_name_price(
            headless=args.headless,
            chromium_sandbox=args.chromium_sandbox,
        )
        if prev is None:
            prev = snap
            print(f"[{_utc_now_iso()}] initial coins={len(prev)}")
        else:
            changes = 0
            for coin, price in snap.items():
                old = prev.get(coin)
                if old is None:
                    continue
                if old != price:
                    changes += 1
                    print(f"[{_utc_now_iso()}] {coin}: {old} -> {price}")
            prev = snap
            print(f"[{_utc_now_iso()}] coins={len(prev)} changes={changes}")

        time.sleep(args.poll_seconds)

    print(f"[{_utc_now_iso()}] done")
    if prev:
        # show a small sample
        sample = list(prev.items())[:10]
        print("sample:", {k: v for k, v in sample})

