#!/usr/bin/env python3
"""Simple parser to convert PubMed-style .txt exports into a CSV table.

Usage:
    python3 parse_pubmed_dir.py --input-dir 1_source_pubmed --output pubmed_summary.csv

The script handles multi-line fields (continuation lines starting with whitespace)
and aggregates repeated tags by joining values with a semicolon.
"""
import argparse
import csv
import os
import re


TAG_RE = re.compile(r"^([A-Za-z0-9]{1,20})\s*-\s*(.*)$")


def parse_file_text(text):
    records = []
    cur = {}
    cur_field = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip():
            # blank line — keep as separator (no-op)
            continue

        m = TAG_RE.match(line)
        if m:
            tag = m.group(1).strip()
            val = m.group(2).strip()
            # New record when we see PMID for an existing cur
            if tag.upper() == "PMID" and cur:
                records.append(cur)
                cur = {}
            # store/append
            key = tag.upper()
            if key in cur:
                # multiple occurrences -> join with semicolon
                cur[key] = cur[key] + "; " + val
            else:
                cur[key] = val
            cur_field = key
        else:
            # continuation line — append to last field (if any)
            if cur_field:
                addition = line.strip()
                if addition:
                    cur[cur_field] = cur.get(cur_field, "") + " " + addition
            else:
                # orphan continuation — ignore or place under NOTE
                cur.setdefault("NOTE", "")
                cur["NOTE"] = (cur["NOTE"] + " " + line.strip()).strip()

    if cur:
        records.append(cur)
    return records


def parse_dir(input_dir):
    all_records = []
    for fname in sorted(os.listdir(input_dir)):
        if not fname.lower().endswith(".txt"):
            continue
        path = os.path.join(input_dir, fname)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        recs = parse_file_text(text)
        all_records.extend(recs)
    return all_records


def write_csv(records, outpath):
    # collect column set
    cols = set()
    for r in records:
        cols.update(r.keys())
    # prefer some common ordering
    preferred = ["PMID", "TI", "AB", "DP", "SO", "TA", "AU", "FAU", "MH"]
    other = sorted([c for c in cols if c not in preferred])
    header = [c for c in preferred if c in cols] + other

    with open(outpath, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=header)
        writer.writeheader()
        for r in records:
            # ensure all keys present
            row = {k: r.get(k, "") for k in header}
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", "-i", required=True, help="input directory")
    parser.add_argument("--output", "-o", default="pubmed_summary.csv")
    args = parser.parse_args()

    records = parse_dir(args.input_dir)
    print(f"Parsed {len(records)} records from {args.input_dir}")
    write_csv(records, args.output)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
