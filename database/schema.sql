-- Forme MySQL 8.0+ starter schema. Application services and migrations are not included.
USE forme;

CREATE TABLE IF NOT EXISTS users (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  email VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  full_name VARCHAR(120) NULL,
  phone VARCHAR(30) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS color_templates (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL UNIQUE,
  color_hex CHAR(7) NOT NULL,
  preview_image_url VARCHAR(500) NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS prosthetics (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  name VARCHAR(150) NOT NULL,
  source_video_url VARCHAR(500) NULL,
  model_url VARCHAR(500) NULL,
  color_template_id BIGINT UNSIGNED NULL,
  custom_color_notes TEXT NULL,
  inspiration_image_url VARCHAR(500) NULL,
  material ENUM('lightweight_polymer','durable_nylon','premium_resin') NOT NULL,
  status ENUM('draft','modeling','ready') NOT NULL DEFAULT 'draft',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_prosthetics_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_prosthetics_color FOREIGN KEY (color_template_id) REFERENCES color_templates(id) ON DELETE SET NULL,
  INDEX idx_prosthetics_user_created (user_id, created_at)
);

CREATE TABLE IF NOT EXISTS orders (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  order_number VARCHAR(40) NOT NULL UNIQUE,
  user_id BIGINT UNSIGNED NOT NULL,
  prosthetic_id BIGINT UNSIGNED NOT NULL,
  amount_hkd DECIMAL(10,2) NULL,
  payment_status ENUM('pending','paid','failed','refunded') NOT NULL DEFAULT 'pending',
  order_status ENUM('placed','modeling','printing','shipped','delivered','cancelled') NOT NULL DEFAULT 'placed',
  placed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_orders_prosthetic FOREIGN KEY (prosthetic_id) REFERENCES prosthetics(id),
  INDEX idx_orders_user_placed (user_id, placed_at)
);

CREATE TABLE IF NOT EXISTS deliveries (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  order_id BIGINT UNSIGNED NOT NULL UNIQUE,
  recipient_name VARCHAR(120) NOT NULL,
  recipient_phone VARCHAR(30) NOT NULL,
  address_line VARCHAR(255) NOT NULL,
  region ENUM('Hong Kong Island','Kowloon','New Territories') NOT NULL,
  district VARCHAR(100) NOT NULL,
  delivery_note TEXT NULL,
  tracking_number VARCHAR(100) NULL,
  carrier VARCHAR(100) NULL,
  delivery_status ENUM('pending','preparing','shipped','out_for_delivery','delivered') NOT NULL DEFAULT 'pending',
  delivered_at DATETIME NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_deliveries_order FOREIGN KEY (order_id) REFERENCES orders(id),
  INDEX idx_deliveries_tracking (tracking_number)
);

INSERT INTO color_templates (name, color_hex) VALUES
  ('Satin Silver', '#AAB6B1'),
  ('Deep Charcoal', '#34403B'),
  ('Soft Sand', '#C7B397'),
  ('Ocean Blue', '#547F90')
ON DUPLICATE KEY UPDATE color_hex = VALUES(color_hex);
