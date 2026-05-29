# Network Inventory Comparator (V5 vs V6)

Single-page browser app: open **`Version_Comparison.html`**, upload both spreadsheets, and click **Compare**.

## Scope

- Only **Blue network** rows: column **AG** must contain the text “Blue network”.
- Choose **V5** and **V6** worksheets independently.
- Files are parsed locally in your browser (nothing is uploaded to a server).

## Analyses

| # | Key column | Value column | Purpose |
|---|------------|--------------|---------|
| 1 | **D** (Request Code) | **W** (Component) | Same request must map to the same component in V5 and V6 |
| 2 | **W** (Component) | **VLAN** (last column with data) | Same component must map to the same VLAN in V5 and V6 |
| 3 | **V6 requests** | **Config TXT** | Templates listed in your TXT vs Blue network rows in V6 |

Optional: upload a **config templates .txt** file (lines like `template VLAN72_INTERFACE_TEMPLATE_50Mbps`) to run Analysis 3.

Both analyses use key-based lookups (row order is ignored). Analysis 2 lists new components in a **New in V6** section; Analysis 1 does not show new request codes. Duplicate keys with conflicting values in one file are flagged as ambiguous.

## Usage

1. Open `Version_Comparison.html` in your browser.
2. Upload **V5** and **V6** Excel files.
3. Select the worksheet for each file.
4. Click **Compare V5 vs V6**.

Results: Analysis 1 first, then Analysis 2.
