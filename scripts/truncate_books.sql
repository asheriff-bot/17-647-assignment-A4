-- Run on Aurora **writer** before Gradescope resubmit if POST /books returns 422 (ISBN already exists).
USE books_db;
TRUNCATE TABLE books;
