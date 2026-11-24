"""Build the attributed FoodGo example and road-time table from public benchmark points only."""

import csv
import hashlib
import io
import json
import math
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "examples"
ARCHIVE = "https://zenodo.org/api/records/3801643/files/foodgo-test-data.zip/content"
ROUTER = "https://router.project-osrm.org/table/v1/driving/"


def fetch(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "FoodRescueDispatch/1.0 research benchmark"}
    )
    with urllib.request.urlopen(req, timeout=50) as response:
        return response.read()


def minute(hhmm):
    h, m = divmod(int(hhmm), 100)
    return h * 60 + m


def write(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def build():
    archive = fetch(ARCHIVE)
    if hashlib.md5(archive).hexdigest() != "82b315217cec5c9b24650edbdab9c2d9":
        raise ValueError("FoodGo archive checksum differs from the published version.")
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:

        def rows(name):
            return list(csv.DictReader(io.StringIO(zipped.read(name).decode("utf-8-sig"))))

        volunteers = rows("foodgo-volunteers.csv")
        orders = rows("foodgo-orders.csv")
    drivers, cases, points = {}, {}, {}
    for v in volunteers:
        n = v["VolunteerID"]
        shifts = [[minute(a), minute(b)] for a, b in json.loads(v["Availability"])]
        start, end = f"V{n}-start", f"V{n}-end"
        if shifts[-1][1] > 930:
            points[start] = [float(v["S-Lon"]), float(v["S-Lat"])]
            points[end] = [float(v["E-Lon"]), float(v["E-Lat"])]
        drivers["V" + n] = {
            "shifts": shifts,
            "capacity": int(v["Capacity"]),
            "load": 1 if n == "29" else 0,
            "position": start,
            "last_seen": 925 if n != "30" else 870,
            "return_to": end,
            "cold_carrier": n != "28",
            "stops": [],
        }
    # Simulated, fixed commitments in addition to the FoodGo availability windows.
    drivers["V27"]["stops"] = [{"place": "P25", "start": 957, "end": 967}]
    drivers["V13"]["stops"] = [{"place": "D24", "start": 982, "end": 992}]
    drivers["V23"]["load"] = 1
    for o in orders:
        n = o["RequestID"]
        if n not in ("24", "25", "26"):
            continue
        for prefix in ("P", "D"):
            points[prefix + n] = [float(o[prefix + "-Lon"]), float(o[prefix + "-Lat"])]
        cases["R" + n] = {
            "as_of": 930,
            "cancelled_driver": "V49",
            "units": int(o["Quantity"]),
            "perishable": o["Perishable"] == "true",
            "pickup": "P" + n,
            "dropoff": "D" + n,
            "pickup_window": [minute(o["P-ET"]), minute(o["P-LT"])],
            "dropoff_window": [minute(o["D-ET"]), minute(o["D-LT"])],
            "max_onboard": 55 if o["Perishable"] == "true" else None,
        }
    # Inject one tight recipient closing time and one missing maximum cold transport time.
    cases["R25"]["dropoff_window"][1] = 940
    cases["R26"]["perishable"] = True
    cases["R26"]["max_onboard"] = None
    keys = list(points)
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in points.values())
    response = json.loads(fetch(ROUTER + coords + "?annotations=duration"))
    if response.get("code") != "Ok":
        raise ValueError("OSRM could not route these points.")
    table = response["durations"]
    if len(table) != len(keys) or any(len(row) != len(keys) for row in table):
        raise ValueError("OSRM table shape does not match the requested places.")
    ROOT.mkdir(exist_ok=True)
    write(
        "dispatch.json",
        {
            "service_date": "2026-11-20",
            "timezone": "America/New_York",
            "handling_minutes": 5,
            "fresh_for": 15,
            "drivers": drivers,
            "cases": cases,
        },
    )
    write(
        "roads.json",
        {
            "source": "OSRM driving / OpenStreetMap",
            "fetched_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "places": keys,
            "minutes": [
                [math.ceil(s / 60) if s is not None else None for s in row] for row in table
            ],
            "snap_metres": {k: round(w["distance"]) for k, w in zip(keys, response["sources"])},
        },
    )
    print(
        f"{len(orders)} source orders, {len(drivers)} drivers, {len(cases)} cases, {len(keys)} routable locations."
    )


if __name__ == "__main__":
    build()
