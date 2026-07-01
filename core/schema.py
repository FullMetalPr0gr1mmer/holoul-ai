"""
The database schema, expressed two ways:

1. `SCHEMA_DDL` — a human/LLM-readable description injected into the Text-to-SQL
   prompt. Because the whole schema is small, we give the model the *complete*
   DDL every time rather than retrieving fragments — this is the single biggest
   accuracy win for Text-to-SQL.
2. `ALLOWED_TABLES` — the allowlist used to validate generated SQL.
"""

ALLOWED_TABLES = [
    "customers",
    "facilities",
    "materials",
    "pickups",
    "pickup_items",
    "data_destruction_jobs",
    "invoices",
    "shipments",
]

SCHEMA_DDL = """
-- Holoul Electronic Recycling — operational database (SQLite dialect)
-- Use SQLite syntax: use LIMIT (not TOP), date() / strftime() for dates.
-- All monetary amounts are in SAR (Saudi Riyal). Weights are in kilograms.

-- Business customers who send e-waste to Holoul.
CREATE TABLE customers (
    customer_id     INTEGER PRIMARY KEY,
    name            TEXT,
    sector          TEXT,   -- 'Government','Telecom','Banking','Healthcare','Technology','Consumer'
    city            TEXT,   -- 'Jeddah','Riyadh','Dammam','Mecca','Medina'
    contact_email   TEXT,
    onboarded_date  TEXT    -- ISO date 'YYYY-MM-DD'
);

-- Holoul processing facilities.
CREATE TABLE facilities (
    facility_id             INTEGER PRIMARY KEY,
    name                    TEXT,
    city                    TEXT,
    address                 TEXT,
    annual_capacity_tonnes  REAL
);

-- Catalogue of accepted material types.
CREATE TABLE materials (
    material_id             INTEGER PRIMARY KEY,
    name                    TEXT,   -- e.g. 'Laptops','Hard Drives','Circuit Boards','Batteries'
    category                TEXT,   -- 'IT Equipment','Consumer Electronics','Storage Media','Components','Batteries'
    is_hazardous            INTEGER,-- 1 = hazardous (e.g. batteries, mercury tubes), else 0
    recovery_value_per_kg   REAL    -- SAR recovered per kg of this material
);

-- A collection event: e-waste picked up from a customer and taken to a facility.
CREATE TABLE pickups (
    pickup_id       INTEGER PRIMARY KEY,
    customer_id     INTEGER REFERENCES customers(customer_id),
    facility_id     INTEGER REFERENCES facilities(facility_id),
    pickup_date     TEXT,   -- ISO date
    status          TEXT,   -- 'Scheduled','Collected','Processing','Completed','Cancelled'
    city            TEXT,
    container_type  TEXT,   -- 'Small Bin','Cage','Stillage','Bulk Loader Bin'
    total_weight_kg REAL    -- total weight collected in this pickup
);

-- Line items: how a pickup's weight breaks down by material.
CREATE TABLE pickup_items (
    item_id     INTEGER PRIMARY KEY,
    pickup_id   INTEGER REFERENCES pickups(pickup_id),
    material_id INTEGER REFERENCES materials(material_id),
    weight_kg   REAL
);

-- Secure data destruction jobs (hard drives, tapes, etc.).
CREATE TABLE data_destruction_jobs (
    job_id          INTEGER PRIMARY KEY,
    customer_id     INTEGER REFERENCES customers(customer_id),
    job_date        TEXT,   -- ISO date
    num_devices     INTEGER,
    method          TEXT,   -- 'Degaussing','Shredding','Physical Destruction'
    certificate_no  TEXT,   -- destruction certificate reference
    cctv_verified   INTEGER -- 1 = destruction recorded on CCTV, else 0
);

-- Invoices issued to customers (usually for a pickup).
CREATE TABLE invoices (
    invoice_id  INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(customer_id),
    pickup_id   INTEGER REFERENCES pickups(pickup_id), -- may be NULL
    issue_date  TEXT,   -- ISO date
    amount_sar  REAL,
    status      TEXT    -- 'Paid','Pending','Overdue'
);

-- Downstream traceability: recovered material sent to recycling partners.
CREATE TABLE shipments (
    shipment_id       INTEGER PRIMARY KEY,
    material_id       INTEGER REFERENCES materials(material_id),
    downstream_partner TEXT,
    weight_kg         REAL,
    shipment_date     TEXT   -- ISO date
);

-- RELATIONSHIPS
--   pickups.customer_id          -> customers.customer_id
--   pickups.facility_id          -> facilities.facility_id
--   pickup_items.pickup_id       -> pickups.pickup_id
--   pickup_items.material_id     -> materials.material_id
--   data_destruction_jobs.customer_id -> customers.customer_id
--   invoices.customer_id         -> customers.customer_id
--   invoices.pickup_id           -> pickups.pickup_id
--   shipments.material_id        -> materials.material_id
"""
