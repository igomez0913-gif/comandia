# Comandia — gestión para restaurantes, cafés y bares (v1.0.0)

Salón con plano de mesas, cuentas y pedidos, comandas por estación (impresora de red y pantalla de cocina), recetas con costo por ingredientes,
inventario, caja y turnos, y facturación SAR de Honduras (CAI, ISV, libros). Funciona sin internet, en un solo equipo o como servidor para varias computadoras.

Usuario de demostración: `luis@miempresa.hn` · clave `comandia123` (cámbiala con el botón **Clave**). Una base nueva arranca con un restaurante de ejemplo
(menú con recetas, descriptivos y dos salones); se limpia en **Configuración › Instalar en un cliente nuevo**.

## Cómo iniciarlo

**Windows, versión portátil (la más fácil):** descomprime `comandia-portatil-<versión>.zip` en `C:\Comandia` y haz doble clic en **`Comandia.exe`**.
Trae su propio Python: no hay que instalar nada ni tener internet. Solo hace falta MySQL 8 o MariaDB; la primera vez te pregunta sus datos.
`crear-acceso-directo.bat` pone los iconos en el escritorio. Se apaga con el icono **Detener Comandia**, `detener.bat` o `Comandia.exe /detener`.

**Windows, versión normal (con Python 3.11 o más nuevo):** descomprime `comandia-<versión>.zip` en `C:\Comandia` y abre `Comandia.exe` (o `iniciar.bat`).
La primera vez instala las librerías (requiere internet).

**Linux/Mac:** `pip install -r requirements.txt` y `./iniciar.sh`.

**Puertos:** en un solo equipo Comandia usa `http://127.0.0.1:8100` (Vértice usa el 8000), así que los dos pueden estar abiertos a la vez; cada uno con su carpeta, su base de datos y su `.secret`.
En modo servidor usa el 443 (HTTPS) y el 80 (instalación); si ese equipo ya tiene otro sistema en esos puertos, edita `servidor.conf` (`puerto_https=8443`, `puerto_http=8080`) **antes** de ejecutar `servidor\instalar-servidor.bat`.

Los datos viven en MySQL/MariaDB (SQLite solo para pruebas). Guarda copia de `.secret` y de la base: son lo único que no se puede regenerar.
Respaldos diarios automáticos en **Configuración › Respaldos**; herramientas: `python comandia_cmd.py <herramienta>` (`setup_mysql`, `actualizar_db`, `resumen_db`, `restaurar`, `servidor`).

Varias computadoras en la red (HTTPS propio, inicio automático): **[servidor/GUIA-SERVIDOR.md](servidor/GUIA-SERVIDOR.md)**.

## Primer día en un restaurante

1. **Configuración › Datos del emisor:** nombre, RTN, dirección y logo. Activa **«Los precios incluyen el ISV»** (el precio del menú es lo que paga el cliente).
2. **Configuración:** carga el CAI que autoriza el SAR y crea usuarios (Mesero, Cajero, Cocina…).
3. **Restaurante › Plano de salones:** dibuja tus salones y mesas (arrastra, gira, nombra). **Impresoras:** la IP de cada estación (cocina, barra…) y *Imprimir prueba*.
4. **Inventario:** crea tus productos con su tipo: *platillo* (se vende, con receta), *insumo* (ingrediente), *elaborado* (se prepara) o *producto* (se compra y se vende tal cual).
   **Restaurante › Recetas:** arma cada receta; el costo y el margen salen solos. **Descriptivos:** «sin cebolla», «término medio», «extra queso» (con recargo opcional).
5. Compras de insumos en **Proveedores / Reabastecer**, y **Conteo físico** para ajustar el inventario.

## Cómo se trabaja

- **Salón** (mesero): toca una mesa → abre cuenta → elige platillos (con descriptivos y notas) → **Enviar a cocina** → la comanda sale en la impresora de la estación y aparece en su pantalla.
  Puede cambiar de mesa, unir cuentas, pasar consumos y dividir por comensal. Anular algo ya enviado pide motivo y el PIN de un supervisor.
  **Dividir la cuenta:** cambiar de comensal un consumo (aun enviado a cocina), partir un plato compartido entre varios comensales (la cocina lo ve una sola vez),
  o dividir toda la cuenta en partes iguales. Los centavos se reparten sin perder ni inventar nada: la suma de las partes es siempre el total.
- **Cocina y barra:** pantalla con *Nuevos / En preparación / Listos*, aviso sonoro y tiempos con color. Al mesero le avisa cuando algo está listo.
- **Caja:** cobra toda la cuenta, por comensal o por consumos; propina sugerida, pago dividido y cambio. Emite la factura SAR, descuenta los ingredientes y cierra la cuenta en una sola operación.
  Abre y cierra **turnos de caja** con cuadre por forma de pago (las propinas entran a lo esperado).
- **Gerencia:** reportes y libros SAR, **productos anulados**, rentabilidad, cuentas por pagar, bancos y bitácora de auditoría.

| Rol | Qué hace |
|---|---|
| **Master / Administrador** | Todo (el Master además administra a otros Master). |
| **Mesero** | Abre cuentas, pide, envía, cambia/une mesas. No cobra ni ve costos; anular lo enviado necesita PIN. |
| **Cajero** | Cobra, abre y cierra su turno. |
| **Cocina** | Solo su pantalla de comandas. |
| **Contador** | Reportes, libros SAR, compras, bancos y costos. |
| Supervisor, Bodeguero | Gerente de turno (aprueba con PIN) y almacén. |

Los permisos se aplican en el servidor, no solo ocultando botones. Se editan en `ROLE_DEFS` (`app/main.py`).

## Impresoras de comandas

Térmicas de red por **IP** (ESC/POS, puerto 9100). Solo se aceptan direcciones de la red local. Si una impresora falla, el pedido sale igual: la comanda queda en la pantalla de cocina y se puede **reimprimir**.
Probado con una impresora simulada; al instalar, usa **Imprimir prueba** y revisa el corte y los acentos en tu modelo.

## Licencias

Planes Básico, Profesional, Empresarial y Todo con claves firmadas (ECDSA) ligadas al código de instalación; prueba de 30 días; funciona sin internet.
Lo que nunca se bloquea: facturar, los reportes del SAR, el respaldo manual y el acceso a los datos. Guía: [herramientas/GUIA-LICENCIAS.md](herramientas/GUIA-LICENCIAS.md).
**La llave privada de firma no va en el repositorio** (`herramientas/llaves/`, ignorada por git): quien la tenga emite licencias.

## Seguridad

Claves con PBKDF2, sesiones JWT con versión de clave, bloqueo de intentos por correo y equipo, cierre por inactividad, cifrado de claves guardadas (SMTP),
cabeceras y CSP estrictas, llaves de API de solo lectura, y bitácora que no se puede editar. Variables útiles: `COMANDIA_SECRET`, `DATABASE_URL`, `COMANDIA_TZ_OFFSET` (por defecto `-6`, Honduras), `COMANDIA_CORS`, `COMANDIA_DOCS=1`.
La licencia sin internet no es infalible: sube el costo de evadirla, no lo elimina.

## Pruebas y empaquetado

```bash
pip install -r requirements-dev.txt
python -m pytest                       # SQLite temporal; TEST_DATABASE_URL=mysql+pymysql://… para MariaDB
windows/build.sh                       # Comandia.exe (MinGW-w64)
windows/build-portable.sh              # dist/comandia-portatil-<versión>.zip
windows/build-normal.sh                # dist/comandia-<versión>.zip
```

Las pruebas de interfaz usan Playwright y Chromium (se omiten solas si no están). Los `.bat` deben ir con saltos de línea CRLF y las herramientas se lanzan con `comandia_cmd.py` (no con `python -m`) para que sirvan también compiladas.

## Estado

Hecho: salón, cuentas, comandas, cocina, recetas, descriptivos, preparación, caja con propinas, SAR, servidor, respaldos y empaquetado.
Pendiente: reservas, domicilio y para llevar, cierre de período, y la compilación protegida con Nuitka (`compilar/`, se ejecuta en Windows).
