-- Run once on the Aurora MySQL WRITER as an admin user (same account you use for init_db.sql),
-- after scripts/init_db.sql has created books_db and customers_db.
--
-- Replace the passwords with the values you set for BOOK_DB_PASSWORD and CUSTOMER_DB_PASSWORD
-- in k8s/deploy.env, then:
--   mysql -h "$RDS_ENDPOINT" -u "$DB_USER" -p"$DB_PASSWORD" < scripts/grant_microservice_mysql_users.sql
--
-- Use distinct usernames matching BOOK_DB_USER and CUSTOMER_DB_USER (e.g. books_rw / customers_rw).

CREATE USER IF NOT EXISTS 'books_rw'@'%' IDENTIFIED BY 'REPLACE_WITH_BOOK_DB_PASSWORD';
GRANT ALL PRIVILEGES ON books_db.* TO 'books_rw'@'%';

CREATE USER IF NOT EXISTS 'customers_rw'@'%' IDENTIFIED BY 'REPLACE_WITH_CUSTOMER_DB_PASSWORD';
GRANT ALL PRIVILEGES ON customers_db.* TO 'customers_rw'@'%';

FLUSH PRIVILEGES;
