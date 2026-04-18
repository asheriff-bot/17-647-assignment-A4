-- OPTIONAL: local / manual testing only. Run after init_db.sql if you want sample rows.
-- Do NOT load this on the same Aurora DB you use for Gradescope — any ISBN collision
-- causes POST /books to return 422 and fails tests (including "LLM Summary").
-- These ISBNs use a rare prefix block (978199...) to avoid overlapping common US test ISBNs (978-0-13-*, 978900*, etc.).
USE books_db;

INSERT INTO books (isbn, title, author, description, genre, price, quantity, summary) VALUES
  ('9781999999001', 'Clean Code', 'Robert Martin', 'A handbook of agile software craftsmanship.', 'non-fiction', 42.00, 10, 'Summary placeholder for Clean Code.'),
  ('9781999999002', 'The Pragmatic Programmer', 'Hunt and Thomas', 'Tips for pragmatic developers.', 'non-fiction', 49.99, 5, 'Summary placeholder for Pragmatic Programmer.'),
  ('9781999999003', 'Effective Java', 'Joshua Bloch', 'Best practices for Java.', 'non-fiction', 54.50, 8, 'Summary placeholder for Effective Java.')
ON DUPLICATE KEY UPDATE title=VALUES(title);
