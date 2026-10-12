File2Base fictional business test dataset
==========================================

Business: Maple & Loom Furniture (fictional furniture retailer)
Purpose: Test File2Base's CSV upload, profiling, primary-key prediction, relationship inference, schema review, SQLite migration, and table browser.

FILES TO UPLOAD TOGETHER
- customers.csv (12 customers)
- suppliers.csv (4 suppliers)
- products.csv (8 products)
- orders.csv (14 orders)
- order_items.csv (22 line items)
- inventory.csv (8 inventory records)

HOW TO TEST
1. Extract this ZIP.
2. Start File2Base in your browser at http://127.0.0.1:5000.
3. Choose the Upload Files option (not necessarily "Load sample workspace").
4. Select all six CSV files in one upload.
5. Run analysis and inspect proposed tables / relationships.
6. Review the schema and create the SQLite database.
7. Browse generated tables and try downloading the database.

EXPECTED RELATIONSHIPS
- orders.customer_id -> customers.customer_id
- order_items.order_id -> orders.order_id
- order_items.product_id -> products.product_id
- products.supplier_id -> suppliers.supplier_id
- inventory.product_id -> products.product_id

DATA QUALITY CASES
- Some optional customer contact values are blank.
- One customer name contains extra spaces.
- Some order discount codes are blank.
These issues are intentional; primary keys and relationship values remain consistent so the core migration can be tested.

All entities, names, addresses/cities, contact details and transactions in these files are fictional. Email addresses use the reserved example.test domain. Phone-like values are synthetic test values.
