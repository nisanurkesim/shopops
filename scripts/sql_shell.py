# Small interactive SQL shell for practicing on the ShopOps database
import sqlite3
import sys
from pathlib import Path

import pandas as pd

# Let this script import config.py from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import DB_PATH

# Show wide tables without cutting columns
pd.set_option("display.max_columns", 20)
pd.set_option("display.width", 200)
pd.set_option("display.max_colwidth", 40)


def main():
    # Read-only: practice queries can never change the data
    con = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    print("ShopOps SQL shell (read-only)")
    print("End a query with ; and press Enter. Type exit to quit.\n")

    buffer = []
    while True:
        try:
            line = input("sql> " if not buffer else "...> ")
        except (EOFError, KeyboardInterrupt):
            break

        if not buffer and line.strip().lower() in ("exit", "quit"):
            break

        buffer.append(line)
        query = "\n".join(buffer).strip()
        if not query.endswith(";"):
            continue  # wait for more lines until the query ends with ;
        buffer = []

        try:
            df = pd.read_sql_query(query, con)
            print(df.to_string(index=False, max_rows=30))
            print(f"({len(df)} rows)\n")
        except Exception as e:
            print("Error:", e, "\n")

    con.close()


if __name__ == "__main__":
    main()