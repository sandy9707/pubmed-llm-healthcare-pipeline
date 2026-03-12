#!/usr/bin/env python3
import pandas as pd
import os


def main():
    # Define input and output paths
    base_dir = "/Volumes/lev/Documents/待完成任务/20260212_摘要下载"
    input_file = os.path.join(base_dir, "1_source_pubmed/pubmed_summary.csv")
    output_dir = os.path.join(base_dir, "2_extracted_data")
    output_file = os.path.join(output_dir, "pubmed_summary_4cols.xlsx")

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    print(f"Loading data from {input_file}...")

    # Read only the first 4 columns to save memory and speed up reading
    try:
        # We can specify usecols=[0, 1, 2, 3] to pick the first four columns
        # (which correspond to PMID, TI, AB, DP based on the downloaded CSV)
        df = pd.read_csv(input_file, usecols=[0, 1, 2, 3])
        print(f"Successfully loaded {len(df)} records. Columns: {list(df.columns)}")

        # Remove duplicates based on PMID or overall rows
        df = df.drop_duplicates(subset=["PMID"])
        print(f"After removing duplicates based on PMID, {len(df)} records remain.")

        print(f"Exporting to Excel file at {output_file}...")
        df.to_excel(output_file, index=False)
        print("Data extraction and export completed successfully!")

    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    main()
