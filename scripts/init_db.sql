-- A3 DB-per-microservice schema (run against Aurora writer).
CREATE DATABASE IF NOT EXISTS customers_db;
CREATE DATABASE IF NOT EXISTS books_db;

USE customers_db;
DROP TABLE IF EXISTS customers;
CREATE TABLE customers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  userId VARCHAR(255) NOT NULL,
  name VARCHAR(255) NOT NULL,
  phone VARCHAR(64) NOT NULL,
  address VARCHAR(255) NOT NULL,
  address2 VARCHAR(255) NULL,
  city VARCHAR(100) NOT NULL,
  state VARCHAR(2) NOT NULL,
  zipcode VARCHAR(20) NOT NULL,
  UNIQUE KEY uq_userId (userId)
);

USE books_db;
DROP TABLE IF EXISTS books;
CREATE TABLE books (
  isbn VARCHAR(32) PRIMARY KEY,
  title VARCHAR(255) NOT NULL,
  author VARCHAR(255) NOT NULL,
  description TEXT NOT NULL,
  genre VARCHAR(64) NOT NULL,
  price DECIMAL(12, 2) NOT NULL,
  quantity INT NOT NULL,
  summary TEXT NULL
);
