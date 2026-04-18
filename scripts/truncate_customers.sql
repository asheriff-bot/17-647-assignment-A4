-- Run on Aurora **writer** before Gradescope resubmit if POST /customers returns 422 (userId already exists).
USE customers_db;
TRUNCATE TABLE customers;
