"""Export JSONL records into CSV tabs ready for Google Sheets import."""

import argparse

from .csv_tabs import export_tabs


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="JSONL input file")
    parser.add_argument("--output-dir", default="data/tabs")
    args = parser.parse_args()
    print(f"Exported {export_tabs(args.input, args.output_dir)} records")