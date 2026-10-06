-- Comandia · MySQL 8 (opcional)
-- Normalmente NO necesitas ejecutar este archivo: configurar-mysql.bat (o la primera vez que abres iniciar.bat)
-- crea la base de datos por ti. Úsalo solo si prefieres crear la base y un usuario propio a mano.
CREATE DATABASE IF NOT EXISTS comandia CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'comandia'@'%' IDENTIFIED BY 'cambia-esta-clave';
GRANT ALL PRIVILEGES ON comandia.* TO 'comandia'@'%';
FLUSH PRIVILEGES;
-- Para crear TODAS las tablas e índices a mano usa schema-completo.sql; si no, Comandia las crea solo al iniciar.
