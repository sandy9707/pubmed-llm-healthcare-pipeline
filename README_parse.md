# pubmed -> CSV parser

This small script converts PubMed-style `.txt` exports (like the ones in
`1_source_pubmed/`) into a single CSV file where each paper is a row and tags
like `PMID`, `TI`, `AB`, `OWN`, `STAT` become columns.

How to run (from repository root):

```bash
python3 parse_pubmed_dir.py --input-dir 1_source_pubmed --output ./1_source_pubmed/pubmed_summary.csv
```

Notes:

- Multi-line fields (e.g. `AB`) are merged into a single cell, with internal
  newlines replaced by spaces.
- Repeated tags (e.g. multiple `MH`, `AU`) are joined with a semicolon and a
  space.
- The script is intentionally simple; if you want Excel-friendly output or more
  normalization (separate rows for multiple authors/mesh terms), I can extend it.
