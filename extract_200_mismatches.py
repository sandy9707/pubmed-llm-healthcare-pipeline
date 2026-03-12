import pandas as pd
import os

INPUT = "/Volumes/lev/Documents/待完成任务/20260212_摘要下载/2_extracted_data/validation_200_results_2models.xlsx"
OUTPUT = "/Volumes/lev/Documents/待完成任务/20260212_摘要下载/3_tuning_results/mismatched_200_details.xlsx"

df = pd.read_excel(INPUT)

columns_of_interest = []
for col in df.columns:
    if col.startswith("Result_"):
        columns_of_interest.append(col)

mismatched = []
for idx, row in df.iterrows():
    results = set()
    for col in columns_of_interest:
        val = str(row[col]).strip()
        if val:
            results.add(val)

    if len(results) > 1:
        # It's a mismatch
        item = {
            "PMID": row.get("PMID", ""),
            "Title": row.get("TI", ""),
            "Abstract": row.get("AB", ""),
        }
        for col in columns_of_interest:
            item[col] = row.get(col, "")
        mismatched.append(item)

os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
if mismatched:
    pd.DataFrame(mismatched).to_excel(OUTPUT, index=False)
    print(f"Found {len(mismatched)} mismatched rows. Exported to {OUTPUT}")
else:
    print("No mismatches found in the 200 rows!")
