#!/usr/bin/env python3
"""
PullList - finds which junkyard parts to pull based on eBay sell-through rate.

Runs nightly on GitHub Actions and publishes docs/index.html (GitHub Pages).

Flow:
  1. Load today's vehicles (vehicles.csv for now; yard scraper plugs in later)
  2. Get an eBay OAuth token (client credentials)
  3. For each vehicle + part: active listings (Browse API) and
     sold in last 90 days (Marketplace Insights API)
  4. Sell-through = sold / active listings
  5. Publish every result to docs/index.html with a threshold slider
  6. Every API call is logged to logs/api_log.txt (proof for eBay's Sandbox review)

Keys come from environment variables EBAY_CLIENT_ID / EBAY_CLIENT_SECRET
(GitHub Secrets), never from files in the repo.

Local usage:
  python pulllist.py --mock     # fake numbers, no keys needed
"""
import argparse
import base64
import csv
import datetime as dt
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
HOSTS = {"sandbox": "https://api.sandbox.ebay.com", "production": "https://api.ebay.com"}
BASE_SCOPE = "https://api.ebay.com/oauth/api_scope"
INSIGHTS_SCOPE = "https://api.ebay.com/oauth/api_scope/buy.marketplace.insights"
PARTS_CATEGORY = "6030"  # eBay Motors: Car & Truck Parts & Accessories

LOG = HERE / "logs" / "api_log.txt"


def log(msg):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f:
        f.write(f"[{stamp}] {msg}\n")
    print(msg)


# ---------- vehicles ----------
def load_vehicles(path):
    with open(path, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("year")]
    log(f"Loaded {len(rows)} vehicles from {Path(path).name}")
    return rows


# ---------- eBay ----------
class EbayClient:
    def __init__(self, cfg):
        self.host = HOSTS[cfg["environment"]]
        self.cfg = cfg
        self.client_id = os.environ.get("EBAY_CLIENT_ID")
        self.client_secret = os.environ.get("EBAY_CLIENT_SECRET")
        if not self.client_id or not self.client_secret:
            sys.exit("Missing EBAY_CLIENT_ID / EBAY_CLIENT_SECRET (add them as GitHub Secrets).")
        self.insights_ok = True
        self.token = self._get_token()

    def _get_token(self):
        auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        url = f"{self.host}/identity/v1/oauth2/token"
        r = None
        for scope in (f"{BASE_SCOPE} {INSIGHTS_SCOPE}", BASE_SCOPE):
            r = requests.post(
                url,
                headers={"Authorization": f"Basic {auth}",
                         "Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "client_credentials", "scope": scope},
                timeout=30,
            )
            log(f"POST /identity/v1/oauth2/token (scope: {scope.split('/')[-1]}) -> {r.status_code}")
            if r.ok:
                if scope == BASE_SCOPE:
                    self.insights_ok = False
                    log("Marketplace Insights scope not granted yet; sold counts unavailable.")
                return r.json()["access_token"]
        sys.exit(f"Could not get token: {r.status_code} {r.text}")

    def _count(self, path, query):
        params = {"q": query, "category_ids": PARTS_CATEGORY, "limit": 1}
        headers = {"Authorization": f"Bearer {self.token}",
                   "X-EBAY-C-MARKETPLACE-ID": self.cfg.get("marketplace", "EBAY_US")}
        r = requests.get(f"{self.host}{path}", params=params, headers=headers, timeout=30)
        log(f"GET {path} q='{query}' -> {r.status_code}")
        time.sleep(self.cfg.get("delay_seconds", 0.3))
        if r.status_code in (401, 403):
            return None
        r.raise_for_status()
        return int(r.json().get("total", 0))

    def active(self, q):
        return self._count("/buy/browse/v1/item_summary/search", q)

    def sold(self, q):
        if not self.insights_ok:
            return None
        n = self._count("/buy/marketplace_insights/v1_beta/item_sales/search", q)
        if n is None:
            self.insights_ok = False
            log("Marketplace Insights denied; continuing without sold counts.")
        return n


class MockClient:
    """Deterministic fake numbers so the whole flow can be tested without keys."""
    insights_ok = True

    def _n(self, q, salt, hi):
        return int(hashlib.md5((q + salt).encode()).hexdigest(), 16) % hi

    def active(self, q):
        return self._n(q, "a", 40) + 1

    def sold(self, q):
        return self._n(q, "s", 40)


# ---------- logic ----------
def sell_through(sold, active):
    if sold is None or active is None:
        return None
    if active == 0:
        return 999.0 if sold > 0 else 0.0  # sells with zero competition
    return round(sold / active * 100, 1)


def run(cfg, client, vehicles):
    results = []
    for v in vehicles:
        car = f'{v["year"]} {v["make"]} {v["model"]}'
        for part in cfg["parts"]:
            q = f"{car} {part}"
            active = client.active(q)
            sold = client.sold(q)
            results.append({"row": v.get("row", ""), "vehicle": car, "part": part,
                            "sold": sold, "active": active,
                            "st": sell_through(sold, active)})
    return results


def write_page(results, cfg, env):
    have_sold = any(r["st"] is not None for r in results)
    data = {
        "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "env": env,
        "threshold": cfg.get("threshold", 50),
        "haveSold": have_sold,
        "results": results,
    }
    template = (HERE / "template.html").read_text()
    page = template.replace("/*__DATA__*/null", json.dumps(data))
    out = HERE / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page)
    log(f"Published docs/index.html ({len(results)} vehicle-part checks, sold data: {have_sold})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args()

    cfg = json.loads((HERE / "config.json").read_text())
    mock = a.mock or os.environ.get("PULLLIST_MOCK") == "true"
    env = "mock" if mock else cfg["environment"]

    LOG.parent.mkdir(exist_ok=True)
    LOG.write_text("")  # fresh log each run
    log(f"=== PullList run | env={env} ===")
    vehicles = load_vehicles(HERE / "vehicles.csv")
    client = MockClient() if mock else EbayClient(cfg)
    write_page(run(cfg, client, vehicles), cfg, env)


if __name__ == "__main__":
    main()
