# Load the Olist CSV files into a local SQLite database
# Full database (eval and local work):
#   python scripts/load_sqlite.py
# Demo sample, the database the demo server builds at start-up:
#   python scripts/load_sqlite.py --sample 0.3 --out data/demo_check.db
import argparse
import random
import sqlite3
import sys
from pathlib import Path

import kagglehub
import pandas as pd

# Let this script import config.py and scripts/ from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import DB_PATH, DEMO_CUSTOMER_A, OLIST_DATASET, SAMPLE_SEED, SIMULATED_TODAY
from scripts.demo_customer import find_demo_customer

# CSV file name -> table name in SQLite
# geolocation (1M rows) is skipped, it is not needed for the basic level
TABLES = {
    "olist_orders_dataset.csv": "orders",
    "olist_order_items_dataset.csv": "order_items",
    "olist_order_payments_dataset.csv": "payments",
    "olist_order_reviews_dataset.csv": "reviews",
    "olist_customers_dataset.csv": "customers",
    "olist_sellers_dataset.csv": "sellers",
    "olist_products_dataset.csv": "products",
    "product_category_name_translation.csv": "category_translation",
}

# Indexes make lookups by these columns fast
INDEXES = [
    "CREATE UNIQUE INDEX idx_orders_order_id ON orders(order_id)",
    "CREATE INDEX idx_orders_customer_id ON orders(customer_id)",
    "CREATE INDEX idx_customers_customer_id ON customers(customer_id)",
    "CREATE INDEX idx_customers_unique_id ON customers(customer_unique_id)",
    "CREATE INDEX idx_items_order_id ON order_items(order_id)",
    "CREATE INDEX idx_payments_order_id ON payments(order_id)",
    "CREATE INDEX idx_reviews_order_id ON reviews(order_id)",
]

# The only table the agent is allowed to write to
RETURN_REQUESTS_SQL = """
CREATE TABLE return_requests (
    return_request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id          TEXT NOT NULL,
    reason            TEXT NOT NULL
                      CHECK (reason IN ('changed_mind', 'damaged', 'wrong_item', 'late')),
    refund_amount     REAL NOT NULL CHECK (refund_amount >= 0),
    status            TEXT NOT NULL
                      CHECK (status IN ('PENDING_REVIEW', 'PENDING_SENIOR', 'APPROVED', 'REJECTED')),
    created_at        TEXT NOT NULL
)
"""

# Sample: keep the customers listed in the temporary table keep_customers
# (column customer_unique_id) and remove every row that belongs to anyone else.
# Run in this order; each statement relies on the one before it.
# sellers, products and category_translation are reference tables and stay whole.
SAMPLE_SQL = [
    # 1. customers: remove the rows of customers who are not kept
    "DELETE FROM customers"
    " WHERE customer_unique_id NOT IN (SELECT customer_unique_id FROM keep_customers)",

    # 2. orders: remove the orders of the removed customers
    # (orders has no customer_unique_id: it is joined through customer_id, one per order)
    "DELETE FROM orders WHERE customer_id NOT IN (SELECT customer_id FROM customers)",

    # 3. order_items, payments, reviews: remove the rows of the removed orders
    "DELETE FROM order_items WHERE order_id NOT IN (SELECT order_id FROM orders)",
    "DELETE FROM payments WHERE order_id NOT IN (SELECT order_id FROM orders)",
    "DELETE FROM reviews WHERE order_id NOT IN (SELECT order_id FROM orders)",
]


def load_csv_files(con, src):
    for csv_name, table in TABLES.items():
        df = pd.read_csv(src / csv_name)
        df.to_sql(table, con, index=False)
        print(f"{table:22} {len(df):>9,} rows loaded")


def apply_r0(con):
    # R0: orders placed on or after SIMULATED_TODAY do not exist in the simulation
    cur = con.execute(
        "DELETE FROM orders WHERE DATE(order_purchase_timestamp) >= DATE(?)",
        (SIMULATED_TODAY,),
    )
    print(f"R0: removed {cur.rowcount} orders placed on or after {SIMULATED_TODAY}")

    # Remove rows in other tables that belonged to the removed orders
    for table in ["order_items", "payments", "reviews"]:
        con.execute(f"DELETE FROM {table} WHERE order_id NOT IN (SELECT order_id FROM orders)")
    con.execute("DELETE FROM customers WHERE customer_id NOT IN (SELECT customer_id FROM orders)")


def choose_customers(con, fraction: float, seed: int, must_keep: list[str]) -> set[str]:
    """A random share of the customers, the same for the same seed, plus must_keep.

    Sampling whole customers (not single orders) keeps every order of a kept customer,
    so "my last order" and "my orders" give the same answer as in the full database.
    """
    ids = [r[0] for r in con.execute(
        "SELECT DISTINCT customer_unique_id FROM customers ORDER BY customer_unique_id")]
    keep = set(random.Random(seed).sample(ids, round(len(ids) * fraction)))
    return keep | set(must_keep)


def apply_sample(con, keep: set[str]):
    """Remove everyone who is not in keep, with the statements in SAMPLE_SQL."""
    if not SAMPLE_SQL:
        raise NotImplementedError("SAMPLE_SQL is empty")
    con.execute("CREATE TEMP TABLE keep_customers (customer_unique_id TEXT PRIMARY KEY)")
    con.executemany("INSERT INTO keep_customers VALUES (?)", [(c,) for c in sorted(keep)])
    for sql in SAMPLE_SQL:
        con.execute(sql)
    con.execute("DROP TABLE keep_customers")


def print_counts(con):
    print("Final row counts:")
    for table in list(TABLES.values()) + ["return_requests"]:
        n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table:22} {n:>9,} rows")


def build_database(db_path: Path = DB_PATH, sample: float | None = None):
    """Build the database at db_path: the full data, or a sample of the customers.

    It is built under another name and renamed at the end, so a build that stops
    half way (for example on the demo server) never leaves a broken database behind.
    """
    # Returns the cached folder, does not download again
    src = Path(kagglehub.dataset_download(OLIST_DATASET))

    db_path = Path(db_path).resolve()   # find_demo_customer needs a full path (--out data/x.db)
    db_path.parent.mkdir(exist_ok=True)
    tmp_path = db_path.with_name(db_path.stem + "_building.db")
    tmp_path.unlink(missing_ok=True)   # left over from a build that stopped

    con = sqlite3.connect(tmp_path)
    load_csv_files(con, src)

    # "with con" saves all changes together, or none if something fails
    with con:
        apply_r0(con)
        for sql in INDEXES:
            con.execute(sql)
        con.execute(RETURN_REQUESTS_SQL)

    if sample is not None:
        # Demo customer B is chosen on the full data, then kept in the sample
        # (the app looks for B again in the sample and finds the same customer)
        customer_b = find_demo_customer(tmp_path)
        demo_customers = [DEMO_CUSTOMER_A] + ([customer_b] if customer_b else [])
        keep = choose_customers(con, sample, SAMPLE_SEED, demo_customers)
        with con:
            apply_sample(con, keep)
        con.execute("VACUUM")   # give back the space of the removed rows: smaller file
        # Mark the file as a sample (percent of customers kept). user_version is a number in
        # the file header, not a table, so the agents and their SQL never see it.
        con.execute(f"PRAGMA user_version = {round(sample * 100)}")
        print(f"Sample: {len(keep):,} customers kept ({sample:.0%}, seed {SAMPLE_SEED})")
        for label, customer in [("A", DEMO_CUSTOMER_A), ("B", customer_b)]:
            n = con.execute("SELECT COUNT(*) FROM customers WHERE customer_unique_id = ?",
                            (customer,)).fetchone()[0]
            print(f"Demo customer {label}: {'kept' if n else 'MISSING'}")

    print_counts(con)
    con.close()
    tmp_path.replace(db_path)
    print("Database written to:", db_path)


def main():
    parser = argparse.ArgumentParser(description="Build the ShopOps SQLite database from Olist")
    parser.add_argument("--sample", type=float, help="keep this share of the customers, e.g. 0.3")
    parser.add_argument("--out", type=Path, default=DB_PATH, help="where to write the database")
    args = parser.parse_args()
    build_database(args.out, args.sample)


if __name__ == "__main__":
    main()
