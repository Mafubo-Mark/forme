-- Forme cloud schema reference; actual initialization uses cloud/app.py.
USE forme_production;


CREATE TABLE audit_events (
	id VARCHAR(32) NOT NULL,
	action VARCHAR(60) NOT NULL,
	target_id VARCHAR(40) NOT NULL,
	actor VARCHAR(40) NOT NULL,
	detail TEXT,
	created_at VARCHAR(40),
	PRIMARY KEY (id)
)

;


CREATE TABLE rate_limits (
	`key` VARCHAR(64) NOT NULL,
	count INTEGER NOT NULL,
	expires_at BIGINT NOT NULL,
	PRIMARY KEY (`key`)
)

;


CREATE TABLE users (
	id INTEGER NOT NULL AUTO_INCREMENT,
	email VARCHAR(254) NOT NULL,
	username VARCHAR(60) NOT NULL,
	password_hash VARCHAR(255) NOT NULL,
	full_name VARCHAR(120),
	phone VARCHAR(40),
	created_at VARCHAR(40),
	PRIMARY KEY (id),
	UNIQUE (email),
	UNIQUE (username)
)

;


CREATE TABLE sessions (
	token_hash VARCHAR(64) NOT NULL,
	user_id INTEGER,
	`role` VARCHAR(15) NOT NULL,
	expires_at BIGINT NOT NULL,
	created_at VARCHAR(40),
	PRIMARY KEY (token_hash),
	FOREIGN KEY(user_id) REFERENCES users (id)
)

;


CREATE TABLE uploads (
	id VARCHAR(32) NOT NULL,
	user_id INTEGER NOT NULL,
	filename VARCHAR(180) NOT NULL,
	content_type VARCHAR(80) NOT NULL,
	byte_size BIGINT NOT NULL,
	sha256 VARCHAR(64),
	status VARCHAR(24),
	created_at VARCHAR(40),
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES users (id)
)

;


CREATE TABLE submissions (
	id VARCHAR(32) NOT NULL,
	user_id INTEGER NOT NULL,
	upload_id VARCHAR(32) NOT NULL,
	template_id VARCHAR(20) NOT NULL,
	color VARCHAR(40) NOT NULL,
	material VARCHAR(40) NOT NULL,
	inspiration TEXT,
	inspiration_file VARCHAR(64),
	status VARCHAR(32),
	model_stage VARCHAR(32),
	model_file VARCHAR(64),
	model_filename VARCHAR(180),
	quote_hkd NUMERIC(10, 2),
	admin_note TEXT,
	created_at VARCHAR(40),
	updated_at VARCHAR(40),
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES users (id),
	UNIQUE (upload_id),
	FOREIGN KEY(upload_id) REFERENCES uploads (id)
)

;


CREATE TABLE modeling_events (
	id VARCHAR(32) NOT NULL,
	submission_id VARCHAR(32) NOT NULL,
	status VARCHAR(32) NOT NULL,
	stage VARCHAR(32) NOT NULL,
	note TEXT,
	actor VARCHAR(30),
	created_at VARCHAR(40),
	PRIMARY KEY (id),
	FOREIGN KEY(submission_id) REFERENCES submissions (id)
)

;


CREATE TABLE orders (
	id VARCHAR(32) NOT NULL,
	order_number VARCHAR(40) NOT NULL,
	user_id INTEGER NOT NULL,
	submission_id VARCHAR(32) NOT NULL,
	amount_hkd NUMERIC(10, 2) NOT NULL,
	payment_status VARCHAR(24),
	order_status VARCHAR(24),
	created_at VARCHAR(40),
	updated_at VARCHAR(40),
	PRIMARY KEY (id),
	UNIQUE (order_number),
	FOREIGN KEY(user_id) REFERENCES users (id),
	UNIQUE (submission_id),
	FOREIGN KEY(submission_id) REFERENCES submissions (id)
)

;


CREATE TABLE deliveries (
	id VARCHAR(32) NOT NULL,
	order_id VARCHAR(32) NOT NULL,
	recipient_name VARCHAR(120) NOT NULL,
	recipient_phone VARCHAR(40) NOT NULL,
	address_line VARCHAR(500) NOT NULL,
	region VARCHAR(100) NOT NULL,
	district VARCHAR(100) NOT NULL,
	delivery_note TEXT,
	carrier VARCHAR(100),
	tracking_number VARCHAR(120),
	delivery_status VARCHAR(24),
	shipped_at VARCHAR(40),
	delivered_at VARCHAR(40),
	confirmed_at VARCHAR(40),
	updated_at VARCHAR(40),
	PRIMARY KEY (id),
	UNIQUE (order_id),
	FOREIGN KEY(order_id) REFERENCES orders (id)
)

;


CREATE TABLE payments (
	id VARCHAR(32) NOT NULL,
	order_id VARCHAR(32) NOT NULL,
	method VARCHAR(80) NOT NULL,
	reference VARCHAR(120),
	proof_file VARCHAR(64),
	proof_filename VARCHAR(180),
	status VARCHAR(24),
	review_note TEXT,
	created_at VARCHAR(40),
	reviewed_at VARCHAR(40),
	PRIMARY KEY (id),
	FOREIGN KEY(order_id) REFERENCES orders (id)
)

;
