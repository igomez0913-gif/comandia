-- Comandia 3.4.4 · Esquema COMPLETO para MySQL 8 / MariaDB 10.4+ (generado de los modelos; no lo edites a mano).
-- Crea la base, el usuario, las 42 tablas con sus llaves foráneas, únicos e índices.
-- Úsalo en una base NUEVA y vacía (una sola vez). Comandia, al iniciar, agrega los datos iniciales (usuario administrador, empresa, catálogos).
-- Si ya tienes una base de una versión anterior NO uses este archivo: usa actualizar-db.bat / actualizar-db.sql.
--
-- Cambia la clave del usuario antes de ejecutar. En MySQL Workbench: abre el archivo y pulsa el rayo (Ejecutar todo).

CREATE DATABASE IF NOT EXISTS comandia CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'comandia'@'%' IDENTIFIED BY 'cambia-esta-clave';
CREATE USER IF NOT EXISTS 'comandia'@'localhost' IDENTIFIED BY 'cambia-esta-clave';
GRANT ALL PRIVILEGES ON comandia.* TO 'comandia'@'%';
GRANT ALL PRIVILEGES ON comandia.* TO 'comandia'@'localhost';
FLUSH PRIVILEGES;

USE comandia;
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- api_keys
CREATE TABLE IF NOT EXISTS api_keys (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(80) NOT NULL, 
	prefix VARCHAR(12), 
	key_hash VARCHAR(64) NOT NULL, 
	created_at DATETIME, 
	created_by VARCHAR(120), 
	last_used DATETIME, 
	active INTEGER, 
	PRIMARY KEY (id), 
	UNIQUE (key_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- audit_log
CREATE TABLE IF NOT EXISTS audit_log (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	created_at DATETIME, 
	user_id INTEGER, 
	user_name VARCHAR(120), 
	action VARCHAR(60) NOT NULL, 
	entity VARCHAR(40), 
	entity_id INTEGER, 
	detail VARCHAR(500), 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX ix_audit_log_created_at ON audit_log (created_at);

-- banks
CREATE TABLE IF NOT EXISTS banks (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(120) NOT NULL, 
	account VARCHAR(40), 
	currency VARCHAR(8), 
	balance NUMERIC(12, 2), 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- cai_ranges
CREATE TABLE IF NOT EXISTS cai_ranges (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	cai VARCHAR(64) NOT NULL, 
	doc_type VARCHAR(2), 
	purpose VARCHAR(10), 
	establishment VARCHAR(3), 
	emission_point VARCHAR(3), 
	range_from INTEGER, 
	range_to INTEGER, 
	current INTEGER, 
	limit_date DATE NOT NULL, 
	received_date DATE, 
	active INTEGER, 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- cash_shifts
CREATE TABLE IF NOT EXISTS cash_shifts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id INTEGER NOT NULL, 
	user_name VARCHAR(120), 
	register VARCHAR(40), 
	store_id INTEGER, 
	opened_at DATETIME, 
	opening NUMERIC(12, 2), 
	status VARCHAR(12), 
	closed_at DATETIME, 
	closed_by VARCHAR(120), 
	summary TEXT, 
	difference NUMERIC(12, 2), 
	note TEXT, 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- clients
CREATE TABLE IF NOT EXISTS clients (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(180) NOT NULL, 
	rtn VARCHAR(20), 
	email VARCHAR(160), 
	phone VARCHAR(40), 
	address VARCHAR(255), 
	initials VARCHAR(4), 
	color VARCHAR(12), 
	price_level INTEGER, 
	exonerated INTEGER, 
	exo_registry VARCHAR(40), 
	sag_registry VARCHAR(40), 
	credit_limit NUMERIC(12, 2), 
	block_overdue INTEGER, 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- company
CREATE TABLE IF NOT EXISTS company (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(160), 
	legal_name VARCHAR(180), 
	rtn VARCHAR(20), 
	address VARCHAR(255), 
	phone VARCHAR(40), 
	email VARCHAR(160), 
	currency VARCHAR(8), 
	logo_path VARCHAR(255), 
	price_names VARCHAR(200), 
	backup_enabled INTEGER, 
	backup_hour INTEGER, 
	backup_keep INTEGER, 
	backup_dir VARCHAR(255), 
	smtp_host VARCHAR(120), 
	smtp_port INTEGER, 
	smtp_user VARCHAR(160), 
	smtp_password VARCHAR(200), 
	smtp_from VARCHAR(160), 
	smtp_security VARCHAR(10), 
	install_id VARCHAR(20), 
	license_key TEXT, 
	trial_start DATE, 
	grandfather_wh INTEGER, 
	pos_enabled INTEGER, 
	idle_minutes INTEGER, 
	prices_include_tax INTEGER, 
	backup_copy_dir VARCHAR(255), 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- counters
CREATE TABLE IF NOT EXISTS counters (
	name VARCHAR(20) NOT NULL, 
	last INTEGER, 
	PRIMARY KEY (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- departments
CREATE TABLE IF NOT EXISTS departments (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(80) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- printers
CREATE TABLE IF NOT EXISTS printers (
	station VARCHAR(20) NOT NULL, 
	host VARCHAR(64), 
	port INTEGER, 
	copies INTEGER, 
	active INTEGER, 
	PRIMARY KEY (station)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- salons
CREATE TABLE IF NOT EXISTS salons (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(60) NOT NULL, 
	sort_order INTEGER, 
	active INTEGER, 
	PRIMARY KEY (id), 
	UNIQUE (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- stores
CREATE TABLE IF NOT EXISTS stores (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	code VARCHAR(3) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	address VARCHAR(255), 
	active INTEGER, 
	PRIMARY KEY (id), 
	UNIQUE (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- suppliers
CREATE TABLE IF NOT EXISTS suppliers (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(180) NOT NULL, 
	rtn VARCHAR(20), 
	email VARCHAR(160), 
	phone VARCHAR(40), 
	category VARCHAR(80), 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- users
CREATE TABLE IF NOT EXISTS users (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(120) NOT NULL, 
	email VARCHAR(160) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	`role` VARCHAR(40), 
	initials VARCHAR(4), 
	active INTEGER, 
	auth_pin VARCHAR(255), 
	store_id INTEGER, 
	PRIMARY KEY (id), 
	UNIQUE (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- warehouses
CREATE TABLE IF NOT EXISTS warehouses (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	code VARCHAR(20) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	address VARCHAR(255), 
	active INTEGER, 
	store_id INTEGER, 
	PRIMARY KEY (id), 
	UNIQUE (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- bank_moves
CREATE TABLE IF NOT EXISTS bank_moves (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	bank_id INTEGER, 
	kind VARCHAR(20), 
	concept VARCHAR(200) NOT NULL, 
	amount NUMERIC(12, 2), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(bank_id) REFERENCES banks (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- cash_moves
CREATE TABLE IF NOT EXISTS cash_moves (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	shift_id INTEGER NOT NULL, 
	kind VARCHAR(12) NOT NULL, 
	amount NUMERIC(12, 2), 
	concept VARCHAR(200), 
	user_name VARCHAR(120), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(shift_id) REFERENCES cash_shifts (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- categories
CREATE TABLE IF NOT EXISTS categories (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(80) NOT NULL, 
	department_id INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(department_id) REFERENCES departments (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- descriptives
CREATE TABLE IF NOT EXISTS descriptives (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(80) NOT NULL, 
	department_id INTEGER, 
	extra_price NUMERIC(12, 2), 
	active INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(department_id) REFERENCES departments (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- documents
CREATE TABLE IF NOT EXISTS documents (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	number VARCHAR(32) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	client_id INTEGER, 
	warehouse_id INTEGER, 
	store_id INTEGER, 
	cai_id INTEGER, 
	status VARCHAR(20), 
	issued_at DATETIME, 
	due_date DATE, 
	notes TEXT, 
	payment_terms VARCHAR(80), 
	validity_date DATE, 
	client_ref VARCHAR(80), 
	exento NUMERIC(12, 2), 
	exonerado NUMERIC(12, 2), 
	gravado_15 NUMERIC(12, 2), 
	gravado_18 NUMERIC(12, 2), 
	isv_15 NUMERIC(12, 2), 
	isv_18 NUMERIC(12, 2), 
	subtotal NUMERIC(12, 2), 
	discount NUMERIC(12, 2), 
	tax NUMERIC(12, 2), 
	total NUMERIC(12, 2), 
	amount_words VARCHAR(255), 
	cai_code VARCHAR(64), 
	range_label VARCHAR(80), 
	limit_date DATE, 
	series_code VARCHAR(8), 
	price_level INTEGER, 
	oce_number VARCHAR(40), 
	buyer_name VARCHAR(180), 
	buyer_rtn VARCHAR(20), 
	discount_auth VARCHAR(120), 
	offline_id VARCHAR(40), 
	credit_auth VARCHAR(120), 
	exo_registry VARCHAR(40), 
	sag_registry VARCHAR(40), 
	ref_document_id INTEGER, 
	user_id INTEGER, 
	user_name VARCHAR(120), 
	PRIMARY KEY (id), 
	UNIQUE (number), 
	FOREIGN KEY(client_id) REFERENCES clients (id), 
	FOREIGN KEY(warehouse_id) REFERENCES warehouses (id), 
	FOREIGN KEY(cai_id) REFERENCES cai_ranges (id), 
	FOREIGN KEY(ref_document_id) REFERENCES documents (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX ix_documents_issued_kind ON documents (issued_at, kind);
CREATE INDEX ix_documents_offline ON documents (offline_id);

-- floor_items
CREATE TABLE IF NOT EXISTS floor_items (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	salon_id INTEGER NOT NULL, 
	kind VARCHAR(12), 
	name VARCHAR(40), 
	shape VARCHAR(12), 
	x INTEGER, 
	y INTEGER, 
	w INTEGER, 
	h INTEGER, 
	rotation INTEGER, 
	seats INTEGER, 
	active INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(salon_id) REFERENCES salons (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- inventory_counts
CREATE TABLE IF NOT EXISTS inventory_counts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	number VARCHAR(30) NOT NULL, 
	warehouse_id INTEGER NOT NULL, 
	status VARCHAR(20), 
	notes VARCHAR(255), 
	user_name VARCHAR(120), 
	created_at DATETIME, 
	applied_at DATETIME, 
	applied_by VARCHAR(120), 
	PRIMARY KEY (id), 
	UNIQUE (number), 
	FOREIGN KEY(warehouse_id) REFERENCES warehouses (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- invoice_series
CREATE TABLE IF NOT EXISTS invoice_series (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	code VARCHAR(8) NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	cai_id INTEGER, 
	current INTEGER, 
	range_to INTEGER, 
	active INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(cai_id) REFERENCES cai_ranges (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- purchases
CREATE TABLE IF NOT EXISTS purchases (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	number VARCHAR(30) NOT NULL, 
	supplier_id INTEGER, 
	warehouse_id INTEGER, 
	cai_supplier VARCHAR(64), 
	status VARCHAR(20), 
	issued_at DATETIME, 
	exento NUMERIC(12, 2), 
	gravado NUMERIC(12, 2), 
	isv NUMERIC(12, 2), 
	total NUMERIC(12, 2), 
	notes TEXT, 
	credit INTEGER, 
	payment_terms VARCHAR(80), 
	due_date DATE, 
	supplier_invoice VARCHAR(40), 
	PRIMARY KEY (id), 
	UNIQUE (number), 
	FOREIGN KEY(supplier_id) REFERENCES suppliers (id), 
	FOREIGN KEY(warehouse_id) REFERENCES warehouses (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- tabs
CREATE TABLE IF NOT EXISTS tabs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	number VARCHAR(16) NOT NULL, 
	name VARCHAR(120), 
	guests INTEGER, 
	status VARCHAR(10), 
	warehouse_id INTEGER, 
	client_id INTEGER, 
	waiter_id INTEGER, 
	waiter_name VARCHAR(120), 
	notes VARCHAR(255), 
	opened_at DATETIME, 
	closed_at DATETIME, 
	merged_into_id INTEGER, 
	PRIMARY KEY (id), 
	UNIQUE (number), 
	FOREIGN KEY(warehouse_id) REFERENCES warehouses (id), 
	FOREIGN KEY(client_id) REFERENCES clients (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- comandas
CREATE TABLE IF NOT EXISTS comandas (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	number VARCHAR(16) NOT NULL, 
	tab_id INTEGER NOT NULL, 
	station VARCHAR(20), 
	created_at DATETIME, 
	printed_at DATETIME, 
	print_error VARCHAR(200), 
	PRIMARY KEY (id), 
	UNIQUE (number), 
	FOREIGN KEY(tab_id) REFERENCES tabs (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- payments
CREATE TABLE IF NOT EXISTS payments (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	document_id INTEGER NOT NULL, 
	amount NUMERIC(12, 2), 
	method VARCHAR(30), 
	bank_id INTEGER, 
	note VARCHAR(200), 
	created_at DATETIME, 
	user_id INTEGER, 
	user_name VARCHAR(120), 
	PRIMARY KEY (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id), 
	FOREIGN KEY(bank_id) REFERENCES banks (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX ix_payments_created ON payments (created_at);

-- products
CREATE TABLE IF NOT EXISTS products (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	sku VARCHAR(40) NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	department_id INTEGER, 
	category_id INTEGER, 
	base_unit VARCHAR(20), 
	cost NUMERIC(12, 2), 
	price NUMERIC(12, 2), 
	price_2 NUMERIC(12, 2), 
	price_3 NUMERIC(12, 2), 
	price_4 NUMERIC(12, 2), 
	min_stock NUMERIC(12, 2), 
	tax_treatment VARCHAR(20), 
	kind VARCHAR(12), 
	station VARCHAR(20), 
	PRIMARY KEY (id), 
	UNIQUE (sku), 
	FOREIGN KEY(department_id) REFERENCES departments (id), 
	FOREIGN KEY(category_id) REFERENCES categories (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- purchase_returns
CREATE TABLE IF NOT EXISTS purchase_returns (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	number VARCHAR(30) NOT NULL, 
	purchase_id INTEGER NOT NULL, 
	credit_note VARCHAR(40), 
	gravado NUMERIC(12, 2), 
	exento NUMERIC(12, 2), 
	isv NUMERIC(12, 2), 
	total NUMERIC(12, 2), 
	notes VARCHAR(255), 
	refund_bank_id INTEGER, 
	user_name VARCHAR(120), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (number), 
	FOREIGN KEY(purchase_id) REFERENCES purchases (id), 
	FOREIGN KEY(refund_bank_id) REFERENCES banks (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- supplier_payments
CREATE TABLE IF NOT EXISTS supplier_payments (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	purchase_id INTEGER NOT NULL, 
	amount NUMERIC(12, 2), 
	method VARCHAR(30), 
	bank_id INTEGER, 
	note VARCHAR(200), 
	user_id INTEGER, 
	user_name VARCHAR(120), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(purchase_id) REFERENCES purchases (id), 
	FOREIGN KEY(bank_id) REFERENCES banks (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- tab_settlements
CREATE TABLE IF NOT EXISTS tab_settlements (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	tab_id INTEGER NOT NULL, 
	document_id INTEGER, 
	tip NUMERIC(12, 2), 
	tip_method VARCHAR(20), 
	`lines` INTEGER, 
	created_at DATETIME, 
	user_id INTEGER, 
	user_name VARCHAR(120), 
	PRIMARY KEY (id), 
	FOREIGN KEY(tab_id) REFERENCES tabs (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- tab_tables
CREATE TABLE IF NOT EXISTS tab_tables (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	tab_id INTEGER NOT NULL, 
	table_id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tab_id) REFERENCES tabs (id), 
	FOREIGN KEY(table_id) REFERENCES floor_items (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- inventory_count_lines
CREATE TABLE IF NOT EXISTS inventory_count_lines (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	count_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	expected NUMERIC(12, 2), 
	counted NUMERIC(12, 2), 
	applied_diff NUMERIC(12, 2), 
	cost NUMERIC(12, 2), 
	PRIMARY KEY (id), 
	FOREIGN KEY(count_id) REFERENCES inventory_counts (id), 
	FOREIGN KEY(product_id) REFERENCES products (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- prep_orders
CREATE TABLE IF NOT EXISTS prep_orders (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	number VARCHAR(16) NOT NULL, 
	product_id INTEGER NOT NULL, 
	warehouse_id INTEGER NOT NULL, 
	qty NUMERIC(12, 4) NOT NULL, 
	cost NUMERIC(12, 4), 
	notes VARCHAR(255), 
	created_at DATETIME, 
	user_id INTEGER, 
	user_name VARCHAR(120), 
	PRIMARY KEY (id), 
	UNIQUE (number), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	FOREIGN KEY(warehouse_id) REFERENCES warehouses (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- presentations
CREATE TABLE IF NOT EXISTS presentations (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	product_id INTEGER, 
	name VARCHAR(80) NOT NULL, 
	unit VARCHAR(20) NOT NULL, 
	factor NUMERIC(12, 4), 
	barcode VARCHAR(40), 
	price NUMERIC(12, 2), 
	price_2 NUMERIC(12, 2), 
	price_3 NUMERIC(12, 2), 
	price_4 NUMERIC(12, 2), 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- recipe_lines
CREATE TABLE IF NOT EXISTS recipe_lines (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	product_id INTEGER NOT NULL, 
	ingredient_id INTEGER NOT NULL, 
	qty NUMERIC(12, 4) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_recipe_ingredient UNIQUE (product_id, ingredient_id), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	FOREIGN KEY(ingredient_id) REFERENCES products (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- stock_moves
CREATE TABLE IF NOT EXISTS stock_moves (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	product_id INTEGER, 
	warehouse_id INTEGER, 
	qty NUMERIC(12, 2), 
	concept VARCHAR(200), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	FOREIGN KEY(warehouse_id) REFERENCES warehouses (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- stocks
CREATE TABLE IF NOT EXISTS stocks (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	product_id INTEGER, 
	warehouse_id INTEGER, 
	qty NUMERIC(12, 2), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_stock UNIQUE (product_id, warehouse_id), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	FOREIGN KEY(warehouse_id) REFERENCES warehouses (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- tab_lines
CREATE TABLE IF NOT EXISTS tab_lines (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	tab_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	description VARCHAR(200), 
	qty NUMERIC(12, 2), 
	unit_price NUMERIC(12, 2), 
	station VARCHAR(20), 
	guest INTEGER, 
	descriptives VARCHAR(255), 
	note VARCHAR(200), 
	status VARCHAR(10), 
	created_at DATETIME, 
	created_by VARCHAR(120), 
	sent_at DATETIME, 
	voided_at DATETIME, 
	voided_by VARCHAR(120), 
	void_reason VARCHAR(200), 
	document_id INTEGER, 
	comanda_id INTEGER, 
	kds_status VARCHAR(12), 
	ready_at DATETIME, 
	served_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tab_id) REFERENCES tabs (id), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id), 
	FOREIGN KEY(comanda_id) REFERENCES comandas (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- document_items
CREATE TABLE IF NOT EXISTS document_items (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	document_id INTEGER, 
	product_id INTEGER, 
	presentation_id INTEGER, 
	description VARCHAR(200) NOT NULL, 
	unit VARCHAR(20), 
	factor NUMERIC(12, 4), 
	qty NUMERIC(12, 2), 
	price NUMERIC(12, 2), 
	discount NUMERIC(12, 2), 
	tax_treatment VARCHAR(20), 
	total NUMERIC(12, 2), 
	cost NUMERIC(12, 4), 
	PRIMARY KEY (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	FOREIGN KEY(presentation_id) REFERENCES presentations (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- purchase_items
CREATE TABLE IF NOT EXISTS purchase_items (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	purchase_id INTEGER, 
	product_id INTEGER, 
	presentation_id INTEGER, 
	description VARCHAR(200) NOT NULL, 
	unit VARCHAR(20), 
	factor NUMERIC(12, 4), 
	qty NUMERIC(12, 2), 
	unit_cost NUMERIC(12, 2), 
	tax_treatment VARCHAR(20), 
	total NUMERIC(12, 2), 
	PRIMARY KEY (id), 
	FOREIGN KEY(purchase_id) REFERENCES purchases (id), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	FOREIGN KEY(presentation_id) REFERENCES presentations (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- purchase_return_items
CREATE TABLE IF NOT EXISTS purchase_return_items (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	return_id INTEGER NOT NULL, 
	purchase_item_id INTEGER NOT NULL, 
	product_id INTEGER, 
	description VARCHAR(200), 
	qty NUMERIC(12, 2), 
	factor NUMERIC(12, 4), 
	unit_cost NUMERIC(12, 2), 
	tax_treatment VARCHAR(20), 
	total NUMERIC(12, 2), 
	PRIMARY KEY (id), 
	FOREIGN KEY(return_id) REFERENCES purchase_returns (id), 
	FOREIGN KEY(purchase_item_id) REFERENCES purchase_items (id), 
	FOREIGN KEY(product_id) REFERENCES products (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


SET FOREIGN_KEY_CHECKS = 1;
