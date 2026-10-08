# Load the Olist CSV files into a local SQLite database
import sqlite3
import sys
from pathlib import Path

import kagglehub
import pandas as pd

# Let this script import config.py from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import DB_PATH, OLIST_DATASET, SIMULATED_TODAY

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


def print_counts(con):
    print("Final row counts:")
    for table in list(TABLES.values()) + ["return_requests"]:
        n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table:22} {n:>9,} rows")


def main():
    # Returns the cached folder, does not download again
    src = Path(kagglehub.dataset_download(OLIST_DATASET))

    # Start from an empty database every time
    DB_PATH.parent.mkdir(exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    con = sqlite3.connect(DB_PATH)
    load_csv_files(con, src)

    # "with con" saves all changes together, or none if something fails
    with con:
        apply_r0(con)
        for sql in INDEXES:
            con.execute(sql)
        con.execute(RETURN_REQUESTS_SQL)

    print_counts(con)
    con.close()
    print("Database written to:", DB_PATH)


if __name__ == "__main__":
    main()