"""
Build and seed the Holoul demo SQLite database with realistic (but entirely
fictional) e-waste recycling data.

Run:  python data/build_db.py
It is idempotent — it drops and recreates every table on each run.
"""
from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "holoul.db"
random.seed(42)  # reproducible data

# ── reference data ────────────────────────────────────────────────────
SECTORS = ["Government", "Telecom", "Banking", "Healthcare", "Technology", "Consumer"]
CITIES = ["Jeddah", "Riyadh", "Dammam", "Mecca", "Medina"]
CONTAINERS = ["Small Bin", "Cage", "Stillage", "Bulk Loader Bin"]
PICKUP_STATUS = ["Completed", "Completed", "Completed", "Processing", "Collected", "Scheduled", "Cancelled"]
DESTRUCTION_METHODS = ["Degaussing", "Shredding", "Physical Destruction"]
INVOICE_STATUS = ["Paid", "Paid", "Paid", "Pending", "Overdue"]
PARTNERS = [
    "Gulf Metals Refining", "Peninsula Plastics Recovery", "Riyadh Smelters Co.",
    "Red Sea Copper Works", "Arabian Rare Earth Recovery",
]

# material name, category, is_hazardous, recovery value SAR/kg
MATERIALS = [
    ("Laptops", "IT Equipment", 0, 14.0),
    ("Desktops", "IT Equipment", 0, 9.5),
    ("Servers", "IT Equipment", 0, 18.0),
    ("Monitors", "Consumer Electronics", 0, 4.0),
    ("Televisions", "Consumer Electronics", 0, 3.5),
    ("Mobile Phones", "Consumer Electronics", 0, 22.0),
    ("Hard Drives", "Storage Media", 0, 12.0),
    ("Solid State Drives", "Storage Media", 0, 20.0),
    ("Tapes & Cartridges", "Storage Media", 0, 2.5),
    ("Circuit Boards", "Components", 0, 35.0),
    ("Cables & Wiring", "Components", 0, 8.0),
    ("Power Supplies", "Components", 0, 6.0),
    ("Batteries", "Batteries", 1, 5.0),
    ("Mercury Tubes", "Batteries", 1, 1.5),
    ("Toner & Ink", "Components", 1, 1.0),
]

COMPANY_PREFIXES = [
    "Al Faisaliah", "Najd", "Tihama", "Rawabi", "Saudi Modern", "Gulf", "Nesma",
    "Alturki", "Bawan", "Almarai", "Jarir", "Mobily", "Zain", "STC", "Riyad",
    "Al Rajhi", "Bupa", "Dr. Sulaiman Habib", "King Fahad", "Aramco Digital",
    "Elm", "Thiqah", "Solutions by STC", "Tamkeen", "Lucidya",
]
COMPANY_SUFFIXES = ["Holding", "Group", "Co.", "LLC", "Industries", "Bank", "Hospital", "Systems", "Telecom", "Authority"]


def daterange(start_days_ago: int, end_days_ago: int = 0) -> str:
    today = date.today()
    delta = random.randint(end_days_ago, start_days_ago)
    return (today - timedelta(days=delta)).isoformat()


def build() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for table in [
        "shipments", "invoices", "data_destruction_jobs", "pickup_items",
        "pickups", "materials", "facilities", "customers",
    ]:
        cur.execute(f"DROP TABLE IF EXISTS {table}")

    cur.executescript(
        """
        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY, name TEXT, sector TEXT, city TEXT,
            contact_email TEXT, onboarded_date TEXT);
        CREATE TABLE facilities (
            facility_id INTEGER PRIMARY KEY, name TEXT, city TEXT, address TEXT,
            annual_capacity_tonnes REAL);
        CREATE TABLE materials (
            material_id INTEGER PRIMARY KEY, name TEXT, category TEXT,
            is_hazardous INTEGER, recovery_value_per_kg REAL);
        CREATE TABLE pickups (
            pickup_id INTEGER PRIMARY KEY, customer_id INTEGER, facility_id INTEGER,
            pickup_date TEXT, status TEXT, city TEXT, container_type TEXT,
            total_weight_kg REAL);
        CREATE TABLE pickup_items (
            item_id INTEGER PRIMARY KEY, pickup_id INTEGER, material_id INTEGER,
            weight_kg REAL);
        CREATE TABLE data_destruction_jobs (
            job_id INTEGER PRIMARY KEY, customer_id INTEGER, job_date TEXT,
            num_devices INTEGER, method TEXT, certificate_no TEXT, cctv_verified INTEGER);
        CREATE TABLE invoices (
            invoice_id INTEGER PRIMARY KEY, customer_id INTEGER, pickup_id INTEGER,
            issue_date TEXT, amount_sar REAL, status TEXT);
        CREATE TABLE shipments (
            shipment_id INTEGER PRIMARY KEY, material_id INTEGER, downstream_partner TEXT,
            weight_kg REAL, shipment_date TEXT);
        """
    )

    # ── facilities ────────────────────────────────────────────────────
    facilities = [
        ("Holoul Jeddah Plant", "Jeddah", "Building 6237, Al Mesk Street, 3rd Industrial Area, Jeddah", 12000.0),
        ("Holoul Riyadh Plant", "Riyadh", "Exit 18, 2nd Industrial City, Riyadh", 9000.0),
        ("Holoul Dammam Hub", "Dammam", "Dammam 2nd Industrial Area, Dammam", 5000.0),
    ]
    cur.executemany(
        "INSERT INTO facilities (name, city, address, annual_capacity_tonnes) VALUES (?,?,?,?)",
        facilities,
    )
    facility_ids = list(range(1, len(facilities) + 1))

    # ── materials ─────────────────────────────────────────────────────
    cur.executemany(
        "INSERT INTO materials (name, category, is_hazardous, recovery_value_per_kg) VALUES (?,?,?,?)",
        MATERIALS,
    )
    material_ids = list(range(1, len(MATERIALS) + 1))

    # ── customers ─────────────────────────────────────────────────────
    n_customers = 45
    customers = []
    for _ in range(n_customers):
        name = f"{random.choice(COMPANY_PREFIXES)} {random.choice(COMPANY_SUFFIXES)}"
        sector = random.choice(SECTORS)
        city = random.choice(CITIES)
        slug = "".join(ch for ch in name.lower() if ch.isalnum())[:14]
        email = f"procurement@{slug}.sa"
        customers.append((name, sector, city, email, daterange(1400, 200)))
    cur.executemany(
        "INSERT INTO customers (name, sector, city, contact_email, onboarded_date) VALUES (?,?,?,?,?)",
        customers,
    )
    customer_ids = list(range(1, n_customers + 1))

    # ── pickups + line items ──────────────────────────────────────────
    n_pickups = 320
    item_id = 0
    for pickup_id in range(1, n_pickups + 1):
        cust = random.choice(customer_ids)
        fac = random.choice(facility_ids)
        status = random.choice(PICKUP_STATUS)
        cust_city = customers[cust - 1][2]
        container = random.choice(CONTAINERS)

        n_items = random.randint(1, 5)
        chosen = random.sample(material_ids, n_items)
        items = []
        total = 0.0
        for mid in chosen:
            base = {"Small Bin": (5, 60), "Cage": (40, 300), "Stillage": (80, 500), "Bulk Loader Bin": (200, 1200)}[container]
            w = round(random.uniform(*base) / n_items, 1)
            items.append((pickup_id, mid, w))
            total += w
        cur.execute(
            "INSERT INTO pickups (pickup_id, customer_id, facility_id, pickup_date, status, city, container_type, total_weight_kg)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (pickup_id, cust, fac, daterange(700, 0), status, cust_city, container, round(total, 1)),
        )
        for it in items:
            item_id += 1
            cur.execute(
                "INSERT INTO pickup_items (item_id, pickup_id, material_id, weight_kg) VALUES (?,?,?,?)",
                (item_id, *it),
            )

    # ── data destruction jobs ─────────────────────────────────────────
    for job_id in range(1, 131):
        cust = random.choice(customer_ids)
        method = random.choice(DESTRUCTION_METHODS)
        cur.execute(
            "INSERT INTO data_destruction_jobs (job_id, customer_id, job_date, num_devices, method, certificate_no, cctv_verified)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                job_id, cust, daterange(700, 0), random.randint(5, 400), method,
                f"HDD-CERT-{2023 + random.randint(0, 2)}-{job_id:04d}",
                1 if random.random() > 0.15 else 0,
            ),
        )

    # ── invoices (one per completed/processing pickup, plus a few standalone) ──
    cur.execute("SELECT pickup_id, customer_id, total_weight_kg, status FROM pickups")
    invoice_id = 0
    for pid, cust, weight, status in cur.fetchall():
        if status in ("Completed", "Processing") and random.random() > 0.1:
            invoice_id += 1
            amount = round(weight * random.uniform(3.0, 9.0) + random.uniform(200, 1500), 2)
            cur.execute(
                "INSERT INTO invoices (invoice_id, customer_id, pickup_id, issue_date, amount_sar, status)"
                " VALUES (?,?,?,?,?,?)",
                (invoice_id, cust, pid, daterange(680, 0), amount, random.choice(INVOICE_STATUS)),
            )

    # ── shipments (downstream traceability) ───────────────────────────
    for shipment_id in range(1, 401):
        mid = random.choice(material_ids)
        cur.execute(
            "INSERT INTO shipments (shipment_id, material_id, downstream_partner, weight_kg, shipment_date)"
            " VALUES (?,?,?,?,?)",
            (shipment_id, mid, random.choice(PARTNERS), round(random.uniform(50, 2500), 1), daterange(650, 0)),
        )

    conn.commit()

    # ── summary ───────────────────────────────────────────────────────
    print(f"Database built at: {DB_PATH}")
    for table in [
        "customers", "facilities", "materials", "pickups", "pickup_items",
        "data_destruction_jobs", "invoices", "shipments",
    ]:
        n = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<24} {n:>6} rows")
    conn.close()


if __name__ == "__main__":
    build()
