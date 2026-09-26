#!/usr/bin/env python3
"""
Scrapes Pull-A-Part's "New On Yard" list and writes vehicles.csv.

It opens the page in a real (headless) browser, waits for the site to load its
vehicle data, and captures that data directly. That way, it keeps working even
if Pull-A-Part changes the page layout.

Debug files (logs/) are saved every run so problems are easy to diagnose.
"""
import csv
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
LOGS = HERE / "logs"

YEAR_KEYS = ("modelyear", "year", "vehicleyear")
MAKE_KEYS = ("makename", "make", "makedesc")
MODEL_KEYS = ("modelname", "model", "modeldesc")
ROW_KEYS = ("row", "rownumber", "rowname", "yardrow")
VIN_KEYS = ("vin", "vinnumber")


def pick(d, keys):
    low = {k.lower(): v for k, v in d.items()}
    for k in keys:
        v = low.get(k)
        if v not in (None, "", {}, []):
            return v
    # VIN is sometimes nested (e.g. vinInformation.vinNumber)
    for v in d.values():
        if isinstance(v, dict):
            inner = pick(v, keys)
            if inner not in (None, ""):
                return inner
    return None


def find_vehicles(node, found):
    """Walk any JSON shape and collect dicts that look like vehicles."""
    if isinstance(node, dict):
        year, make, model = pick(node, YEAR_KEYS), pick(node, MAKE_KEYS), pick(node, MODEL_KEYS)
        if year and make and model and not isinstance(make, (dict, list)):
            found.append({
                "year": str(year).strip(),
                "make": str(make).strip().title(),
                "model": str(model).strip().title(),
                "row": str(pick(node, ROW_KEYS) or "").strip(),
                "vin": str(pick(node, VIN_KEYS) or "").strip(),
            })
            return
        for v in node.values():
            find_vehicles(v, found)
    elif isinstance(node, list):
        for v in node:
            find_vehicles(v, found)


def scrape(url):
    captured = []
    LOGS.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"))

        def on_response(resp):
            if "json" in (resp.headers.get("content-type") or ""):
                try:
                    captured.append({"url": resp.url, "data": resp.json()})
                except Exception:
                    pass

        page.on("response", on_response)
        page.goto(url, wait_until="networkidle", timeout=90_000)
        page.wait_for_timeout(8_000)  # results load after the page settles
        (LOGS / "yard_page.html").write_text(page.content())
        browser.close()

    (LOGS / "yard_raw.json").write_text(json.dumps(captured, indent=1, default=str)[:2_000_000])
    vehicles = []
    for c in captured:
        find_vehicles(c["data"], vehicles)

    seen, unique = set(), []
    for v in vehicles:
        key = v["vin"] or (v["year"], v["make"], v["model"], v["row"])
        if key not in seen:
            seen.add(key)
            unique.append(v)
    print(f"Captured {len(captured)} data responses, found {len(unique)} vehicles")
    return unique


def main():
    cfg = json.loads((HERE / "config.json").read_text())
    vehicles = scrape(cfg["yard_url"])
    if not vehicles:
        sys.exit("No vehicles found. Keeping the previous vehicles.csv. "
                 "Check logs/yard_raw.json and logs/yard_page.html.")
    with (HERE / "vehicles.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["year", "make", "model", "row", "vin"])
        w.writeheader()
        w.writerows(vehicles)
    print(f"Wrote {len(vehicles)} vehicles to vehicles.csv")


if __name__ == "__main__":
    main()
