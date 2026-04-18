-- Clear books + customers on the Aurora **writer** before a Gradescope submit if you see:
--   POST /books  -> 422 (ISBN already exists) — also breaks "LLM Summary" test (422 != 201)
--   POST /customers -> 422 (userId already exists)
-- Safe: no foreign keys between these tables in A2 schema.
USE books_db;
TRUNCATE TABLE books;

USE customers_db;
TRUNCATE TABLE customers;
