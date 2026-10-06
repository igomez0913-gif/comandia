# Guía de licencias (solo para el desarrollador)

## Los planes
| Plan | Clave | Módulos |
|---|---|---|
| Básico | no necesita (opcional: `--plan basico`, opción 1 del menú) | facturación SAR, cotizaciones, POS, clientes, inventario (1 bodega), compras de contado, usuarios, turnos, reportes SAR, respaldo manual |
| Profesional | `--plan profesional` | multi_warehouse, reports, backup, api, importar_excel, etiquetas |
| Empresarial | `--plan empresarial` | todo lo anterior + whatsapp, email, offline, compras, advanced_credit, reabastecimiento, docs_fiscales, multi_tienda |
| Todo | `--plan todo` | todos los módulos, **incluidos los que se creen después** |

Para cambiar qué módulo pertenece a qué plan, edita `PLANS` en `app/licencia.py` (y `tier` se ajusta solo en la pantalla). Las claves ya emitidas llevan la lista de módulos, así que **cambiar un plan no afecta a las claves viejas**; solo `--plan todo` se actualiza solo.

## Primera vez
1. `python herramientas/generador-de-claves.py crear-llaves` (o doble clic en `generador-de-claves.bat`).
2. Guarda `herramientas/llaves/privada.pem` en 2 lugares seguros (USB y nube privada). **Si la pierdes no puedes emitir más claves; si se filtra, cualquiera puede.**
3. Sube `app/llave_publica.pem` y `app/llave_embebida.py` al repositorio y arma de nuevo los zip: **sin esos archivos el sistema queda sin candados.**

## Vender un plan
1. El cliente instala Comandia y te envía el **código de instalación** (Configuración › Licencia y módulos, formato `ABCD-EFGH`).
2. Emite la clave:
```
python herramientas/generador-de-claves.py emitir --cliente "Ferretería Toty Depot" --instalacion ABCD-EFGH --plan empresarial --usuarios 5
```
   Sin argumentos el generador abre un menú: 1 Básico · 2 Profesional · 3 Empresarial · 4 Todo · 5 Personalizado (módulos sueltos). Una **clave Básica** (`--plan basico`) sirve para cerrar la prueba de 30 días de una vez y dejar al cliente en Básico con sus límites (usuarios, cajas) o con vencimiento. En general una clave válida, del plan que sea, da por terminada la prueba.
   Opciones: `--plan basico|profesional|empresarial|todo`, `--modulos whatsapp,api` (se suman al plan, aceptan los nombres anteriores), `--bodegas N`, `--tiendas N`, `--usuarios N`, `--cajas N` (0 = sin límite), `--meses 12` o `--vence AAAA-MM-DD` (por defecto perpetua).
3. Envíale la clave; la pega en Configuración › Licencia y módulos › Activar clave. Todo queda anotado en `herramientas/claves-emitidas.csv`.
4. Para ampliar (pasar de Profesional a Empresarial): emite otra clave con el **mismo código de instalación**; la nueva reemplaza a la anterior.

## Renovar / revocar
- Con vencimiento: emite una clave nueva con otra fecha. Al vencer, el cliente vuelve al plan Básico (no pierde datos ni puede dejar de facturar).
- Las claves no se pueden revocar a distancia (el sistema funciona sin internet): la forma de «quitar» una licencia es no renovarla.

## Comprobar
`python herramientas/generador-de-claves.py verificar CLAVE` muestra el paquete, los módulos y los límites.
