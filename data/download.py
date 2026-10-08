# Download the Olist dataset from Kaggle and list the CSV files
import kagglehub
from pathlib import Path

path = kagglehub.dataset_download("olistbr/brazilian-ecommerce")
print("Downloaded to:", path)

csv_files = sorted(Path(path).glob("*.csv"))
print("Number of CSV files:", len(csv_files))

for f in csv_files:
    size_mb = f.stat().st_size / 1_000_000
    print(f"{f.name:50} {size_mb:6.1f} MB")