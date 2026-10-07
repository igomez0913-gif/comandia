-- Comandia · actualizar la base de datos MySQL a la versión actual (v2.9). Sirve desde la v2.3 en adelante.
-- NORMALMENTE NO HACE FALTA: Comandia aplica estos cambios solo al iniciar, y actualizar-db.bat los aplica con respaldo previo.
-- Úsalo si prefieres hacerlo a mano desde MySQL Workbench. Se puede ejecutar varias veces: lo que ya existe no se toca.
-- ANTES: respalda la base (Server > Data Export en Workbench) y cierra Comandia.
-- Cambia el nombre de la base si no se llama comandia:
USE comandia;
SET NAMES utf8mb4;
-- MySQL Workbench trae activado el «modo seguro» (error 1175). Se apaga solo para este script y al final se deja como estaba.
SET @comandia_safe_updates = @@SQL_SAFE_UPDATES;
SET SQL_SAFE_UPDATES = 0;

-- 1) Tabla nueva: bitácora de auditoría (v2.6)
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER NOT NULL AUTO_INCREMENT,
  created_at DATETIME,
  user_id INTEGER,
  user_name VARCHAR(120),
  action VARCHAR(60) NOT NULL,
  entity VARCHAR(40),
  entity_id INTEGER,
  detail VARCHAR(500),
  PRIMARY KEY (id),
  INDEX ix_audit_log_created_at (created_at)
) DEFAULT CHARSET=utf8mb4;

-- Tabla nueva: tiendas / sucursales (módulo Multi-tienda)
CREATE TABLE IF NOT EXISTS stores (
  id INTEGER NOT NULL AUTO_INCREMENT,
  code VARCHAR(3) NOT NULL,
  name VARCHAR(120) NOT NULL,
  address VARCHAR(255),
  active INTEGER,
  PRIMARY KEY (id),
  UNIQUE (code)
) DEFAULT CHARSET=utf8mb4;

-- Tablas nuevas del restaurante: recetas, descriptivos y órdenes de preparación
CREATE TABLE IF NOT EXISTS recipe_lines (
  id INTEGER NOT NULL AUTO_INCREMENT, 
  product_id INTEGER NOT NULL, 
  ingredient_id INTEGER NOT NULL, 
  qty NUMERIC(12, 4) NOT NULL, 
  PRIMARY KEY (id), 
  CONSTRAINT uq_recipe_ingredient UNIQUE (product_id, ingredient_id), 
  FOREIGN KEY(product_id) REFERENCES products (id), 
  FOREIGN KEY(ingredient_id) REFERENCES products (id)
) DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS descriptives (
  id INTEGER NOT NULL AUTO_INCREMENT, 
  name VARCHAR(80) NOT NULL, 
  department_id INTEGER, 
  extra_price NUMERIC(12, 2), 
  active INTEGER, 
  PRIMARY KEY (id), 
  FOREIGN KEY(department_id) REFERENCES departments (id)
) DEFAULT CHARSET=utf8mb4;

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
) DEFAULT CHARSET=utf8mb4;

-- Tablas nuevas del salón y la cocina: salones, plano, cuentas, pedidos, cobros, comandas e impresoras
CREATE TABLE IF NOT EXISTS salons (
  id INTEGER NOT NULL AUTO_INCREMENT, 
  name VARCHAR(60) NOT NULL, 
  sort_order INTEGER, 
  active INTEGER, 
  PRIMARY KEY (id), 
  UNIQUE (name)
) DEFAULT CHARSET=utf8mb4;

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
) DEFAULT CHARSET=utf8mb4;

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
) DEFAULT CHARSET=utf8mb4;

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
) DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS tab_tables (
  id INTEGER NOT NULL AUTO_INCREMENT, 
  tab_id INTEGER NOT NULL, 
  table_id INTEGER NOT NULL, 
  PRIMARY KEY (id), 
  FOREIGN KEY(tab_id) REFERENCES tabs (id), 
  FOREIGN KEY(table_id) REFERENCES floor_items (id)
) DEFAULT CHARSET=utf8mb4;

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
  share NUMERIC(12, 8), 
  group_id INTEGER, 
  comanda_id INTEGER, 
  kds_status VARCHAR(12), 
  ready_at DATETIME, 
  served_at DATETIME, 
  PRIMARY KEY (id), 
  FOREIGN KEY(tab_id) REFERENCES tabs (id), 
  FOREIGN KEY(product_id) REFERENCES products (id), 
  FOREIGN KEY(document_id) REFERENCES documents (id), 
  FOREIGN KEY(comanda_id) REFERENCES comandas (id)
) DEFAULT CHARSET=utf8mb4;

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
) DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS printers (
  station VARCHAR(20) NOT NULL, 
  host VARCHAR(64), 
  port INTEGER, 
  copies INTEGER, 
  active INTEGER, 
  PRIMARY KEY (station)
) DEFAULT CHARSET=utf8mb4;

-- Tabla nueva: contadores de numeración (OC-, CT-, CF-...), para que varios usuarios a la vez no repitan número
CREATE TABLE IF NOT EXISTS counters (
  name VARCHAR(20) NOT NULL,
  last INTEGER,
  PRIMARY KEY (name)
) DEFAULT CHARSET=utf8mb4;

-- Tabla nueva: llaves de acceso de la API de lectura (módulo API)
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
) DEFAULT CHARSET=utf8mb4;

-- Tabla nueva: pagos a proveedores (v2.9)
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
) DEFAULT CHARSET=utf8mb4;

-- Tablas nuevas: devoluciones a proveedores y conteos físicos (v2.9)
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
) DEFAULT CHARSET=utf8mb4;

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
) DEFAULT CHARSET=utf8mb4;

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
) DEFAULT CHARSET=utf8mb4;

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
) DEFAULT CHARSET=utf8mb4;

-- Tablas nuevas: turnos de caja y sus movimientos de efectivo (v2.9)
CREATE TABLE IF NOT EXISTS cash_shifts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id INTEGER NOT NULL, 
	user_name VARCHAR(120), 
	register VARCHAR(40), 
	opened_at DATETIME, 
	opening NUMERIC(12, 2), 
	status VARCHAR(12), 
	closed_at DATETIME, 
	closed_by VARCHAR(120), 
	summary TEXT, 
	difference NUMERIC(12, 2), 
	note TEXT, 
	PRIMARY KEY (id)
) DEFAULT CHARSET=utf8mb4;

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
) DEFAULT CHARSET=utf8mb4;

-- 2) Columnas nuevas (solo se agregan si faltan)
DROP PROCEDURE IF EXISTS comandia_add_column;
DELIMITER $$
CREATE PROCEDURE comandia_add_column(IN t VARCHAR(64), IN c VARCHAR(64), IN ddl VARCHAR(255))
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = t)
     AND NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = t AND COLUMN_NAME = c) THEN
    SET @comandia_sql = CONCAT('ALTER TABLE `', t, '` ADD COLUMN `', c, '` ', ddl);
    PREPARE st FROM @comandia_sql;
    EXECUTE st;
    DEALLOCATE PREPARE st;
  END IF;
END$$
DELIMITER ;

CALL comandia_add_column('documents', 'payment_terms', 'VARCHAR(80) DEFAULT ''Contado''');
CALL comandia_add_column('documents', 'validity_date', 'DATE NULL');
CALL comandia_add_column('documents', 'client_ref', 'VARCHAR(80) DEFAULT ''''');
CALL comandia_add_column('documents', 'series_code', 'VARCHAR(8) DEFAULT ''''');
CALL comandia_add_column('documents', 'ref_document_id', 'INTEGER NULL');
CALL comandia_add_column('documents', 'user_id', 'INTEGER NULL');
CALL comandia_add_column('documents', 'user_name', 'VARCHAR(120) DEFAULT ''''');
CALL comandia_add_column('payments', 'user_id', 'INTEGER NULL');
CALL comandia_add_column('payments', 'user_name', 'VARCHAR(120) DEFAULT ''''');
CALL comandia_add_column('company', 'logo_path', 'VARCHAR(255) DEFAULT ''''');
CALL comandia_add_column('company', 'price_names', 'VARCHAR(200) DEFAULT ''Público|Mayorista|Distribuidor|Especial''');
CALL comandia_add_column('clients', 'price_level', 'INTEGER DEFAULT 1');
CALL comandia_add_column('company', 'backup_enabled', 'INTEGER DEFAULT 1');
CALL comandia_add_column('company', 'backup_hour', 'INTEGER DEFAULT 12');
CALL comandia_add_column('company', 'backup_keep', 'INTEGER DEFAULT 30');
CALL comandia_add_column('company', 'backup_dir', 'VARCHAR(255) DEFAULT ''''');
CALL comandia_add_column('products', 'price_2', 'DECIMAL(12,2) DEFAULT 0');
CALL comandia_add_column('products', 'price_3', 'DECIMAL(12,2) DEFAULT 0');
CALL comandia_add_column('products', 'price_4', 'DECIMAL(12,2) DEFAULT 0');
CALL comandia_add_column('presentations', 'price_2', 'DECIMAL(12,2) DEFAULT 0');
CALL comandia_add_column('presentations', 'price_3', 'DECIMAL(12,2) DEFAULT 0');
CALL comandia_add_column('presentations', 'price_4', 'DECIMAL(12,2) DEFAULT 0');
CALL comandia_add_column('documents', 'price_level', 'INTEGER DEFAULT 1');
CALL comandia_add_column('users', 'active', 'TINYINT DEFAULT 1');
CALL comandia_add_column('clients', 'exonerated', 'INTEGER DEFAULT 0');
CALL comandia_add_column('clients', 'exo_registry', 'VARCHAR(40) DEFAULT ''''');
CALL comandia_add_column('clients', 'sag_registry', 'VARCHAR(40) DEFAULT ''''');
CALL comandia_add_column('documents', 'oce_number', 'VARCHAR(40) DEFAULT ''''');
CALL comandia_add_column('documents', 'exo_registry', 'VARCHAR(40) DEFAULT ''''');
CALL comandia_add_column('documents', 'sag_registry', 'VARCHAR(40) DEFAULT ''''');
CALL comandia_add_column('company', 'smtp_host', 'VARCHAR(120) DEFAULT ''''');
CALL comandia_add_column('company', 'smtp_port', 'INTEGER DEFAULT 587');
CALL comandia_add_column('company', 'smtp_user', 'VARCHAR(160) DEFAULT ''''');
CALL comandia_add_column('company', 'smtp_password', 'VARCHAR(200) DEFAULT ''''');
CALL comandia_add_column('company', 'smtp_from', 'VARCHAR(160) DEFAULT ''''');
CALL comandia_add_column('company', 'smtp_security', 'VARCHAR(10) DEFAULT ''starttls''');
CALL comandia_add_column('company', 'install_id', 'VARCHAR(20) DEFAULT ''''');
CALL comandia_add_column('company', 'license_key', 'TEXT NULL');
CALL comandia_add_column('company', 'trial_start', 'DATE NULL');
CALL comandia_add_column('company', 'grandfather_wh', 'INTEGER NULL');
CALL comandia_add_column('company', 'pos_enabled', 'INTEGER DEFAULT 1');
CALL comandia_add_column('cash_shifts', 'store_id', 'INTEGER NULL');
CALL comandia_add_column('company', 'idle_minutes', 'INTEGER DEFAULT 30');
CALL comandia_add_column('company', 'backup_copy_dir', 'VARCHAR(255) DEFAULT ''''');
CALL comandia_add_column('cai_ranges', 'purpose', 'VARCHAR(10) DEFAULT ''''');
CALL comandia_add_column('users', 'store_id', 'INTEGER NULL');
CALL comandia_add_column('warehouses', 'store_id', 'INTEGER NULL');
CALL comandia_add_column('documents', 'store_id', 'INTEGER NULL');
CALL comandia_add_column('purchases', 'credit', 'INTEGER DEFAULT 0');
CALL comandia_add_column('purchases', 'payment_terms', 'VARCHAR(80) DEFAULT ''Contado''');
CALL comandia_add_column('purchases', 'due_date', 'DATE NULL');
CALL comandia_add_column('purchases', 'supplier_invoice', 'VARCHAR(40) DEFAULT ''''');
CALL comandia_add_column('document_items', 'cost', 'DECIMAL(12,4) NULL');
CALL comandia_add_column('products', 'kind', 'VARCHAR(12) DEFAULT ''producto''');
CALL comandia_add_column('products', 'station', 'VARCHAR(20) DEFAULT ''''');
CALL comandia_add_column('company', 'prices_include_tax', 'INTEGER DEFAULT 0');
CALL comandia_add_column('tab_lines', 'share', 'DECIMAL(12,8) NULL');
CALL comandia_add_column('tab_lines', 'group_id', 'INTEGER NULL');
CALL comandia_add_column('tab_lines', 'orig_guest', 'INTEGER NULL');
CALL comandia_add_column('documents', 'buyer_name', 'VARCHAR(180) DEFAULT ''''');
CALL comandia_add_column('documents', 'buyer_rtn', 'VARCHAR(20) DEFAULT ''''');
CALL comandia_add_column('cai_ranges', 'received_date', 'DATE NULL');
CALL comandia_add_column('document_items', 'discount', 'DECIMAL(12,2) DEFAULT 0');
CALL comandia_add_column('documents', 'discount', 'DECIMAL(12,2) DEFAULT 0');
CALL comandia_add_column('documents', 'discount_auth', 'VARCHAR(120) DEFAULT ''''');
CALL comandia_add_column('documents', 'offline_id', 'VARCHAR(40) DEFAULT ''''');
CALL comandia_add_column('users', 'auth_pin', 'VARCHAR(255) DEFAULT ''''');
CALL comandia_add_column('clients', 'credit_limit', 'DECIMAL(12,2) DEFAULT 0');
CALL comandia_add_column('clients', 'block_overdue', 'INTEGER DEFAULT 1');
CALL comandia_add_column('documents', 'credit_auth', 'VARCHAR(120) DEFAULT ''''');
DROP PROCEDURE IF EXISTS comandia_add_column;

-- Columnas que se hacen más precisas (cantidades facturadas a 8 decimales, existencias a 4). Solo se cambian si todavía tienen menos decimales.
DROP PROCEDURE IF EXISTS comandia_widen_column;
DELIMITER $$
CREATE PROCEDURE comandia_widen_column(IN t VARCHAR(64), IN c VARCHAR(64), IN ddl VARCHAR(255), IN scale_wanted INT)
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = t AND COLUMN_NAME = c AND NUMERIC_SCALE < scale_wanted) THEN
    SET @comandia_sql = CONCAT('ALTER TABLE `', t, '` MODIFY COLUMN `', c, '` ', ddl);
    PREPARE st FROM @comandia_sql;
    EXECUTE st;
    DEALLOCATE PREPARE st;
  END IF;
END$$
DELIMITER ;
CALL comandia_widen_column('document_items', 'qty', 'DECIMAL(16,8) NULL', 8);
CALL comandia_widen_column('stocks', 'qty', 'DECIMAL(14,4) NULL', 4);
CALL comandia_widen_column('stock_moves', 'qty', 'DECIMAL(14,4) NULL', 4);
DROP PROCEDURE IF EXISTS comandia_widen_column;

-- Índices por fecha (listados y reportes más rápidos con muchos documentos). Se crean solo si faltan.
DROP PROCEDURE IF EXISTS comandia_add_index;
DELIMITER $$
CREATE PROCEDURE comandia_add_index(IN t VARCHAR(64), IN i VARCHAR(64), IN cols VARCHAR(255))
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = t)
     AND NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = t AND INDEX_NAME = i) THEN
    SET @comandia_sql = CONCAT('CREATE INDEX `', i, '` ON `', t, '` (', cols, ')');
    PREPARE st FROM @comandia_sql;
    EXECUTE st;
    DEALLOCATE PREPARE st;
  END IF;
END$$
DELIMITER ;
CALL comandia_add_index('documents', 'ix_documents_issued_kind', 'issued_at, kind');
CALL comandia_add_index('documents', 'ix_documents_offline', 'offline_id');
CALL comandia_add_index('payments', 'ix_payments_created', 'created_at');
DROP PROCEDURE IF EXISTS comandia_add_index;

-- 3) Usuarios de versiones anteriores a la v2.5: todos activos y al menos un Master
UPDATE users SET active = 1 WHERE id > 0 AND active IS NULL;
UPDATE users SET role = 'Master'
 WHERE id = (SELECT id FROM (SELECT id FROM users WHERE role = 'Administrador' ORDER BY id LIMIT 1) primero)
   AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM users WHERE role = 'Master') m);
SET SQL_SAFE_UPDATES = @comandia_safe_updates;

-- 4) Comprobación: debe mostrar 1 tabla y las columnas nuevas
SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA = DATABASE()
   AND ((TABLE_NAME = 'audit_log' AND COLUMN_NAME = 'id')
        OR COLUMN_NAME IN ('ref_document_id', 'user_id', 'user_name', 'price_level', 'price_names', 'price_2', 'price_3', 'price_4',
                           'backup_enabled', 'backup_hour', 'backup_keep', 'backup_dir',
                           'kind', 'station', 'prices_include_tax', 'share', 'group_id', 'orig_guest', 'exonerated', 'exo_registry', 'sag_registry', 'oce_number', 'smtp_host', 'received_date', 'discount', 'discount_auth', 'auth_pin', 'credit_limit', 'block_overdue', 'credit_auth', 'offline_id', 'install_id'))
 ORDER BY TABLE_NAME, COLUMN_NAME;
