# Comandia · guía de instalación multiusuario

Un equipo hace de **servidor** (guarda la base de datos y corre Comandia); las demás computadoras de la red entran por el navegador. En los clientes **no se instala nada**, solo se confía una vez en el certificado de seguridad.

```
 PC caja 1 ─┐
 PC caja 2 ─┼── red local ──►  SERVIDOR  (Comandia + MySQL)   https://comandia
 Laptop    ─┘
```

## Qué necesita el servidor
- Windows 10/11 Pro o Windows Server, 4 GB de RAM (8 recomendado), disco SSD.
- **MySQL o MariaDB** instalado en el mismo equipo (MariaDB 10.6 o más nuevo). Anota la clave del usuario `root`.
- **IP fija**: en el router, «reserva de DHCP» para ese equipo (o IP estática en Windows).
- Conviene un **UPS** (batería) y un **disco o carpeta aparte para los respaldos**.
- Los usuarios ven al servidor por su **nombre** (por ejemplo `comandia`) o por su **IP**. Un nombre amigable lo da el DNS del router o el archivo `hosts` de cada PC; si no, se usa la IP.

## Instalar el servidor (una vez, ~10 minutos)
1. Instala MySQL/MariaDB y comprueba que el servicio está iniciado.
2. Descomprime el zip **portátil** de Comandia en `C:\Comandia`.
3. Abre la carpeta `servidor` y haz **clic derecho › Ejecutar como administrador** en `instalar-servidor.bat`.
4. Responde lo que pide: datos de MySQL (primera vez), y el **nombre o IP** con que entrarán los usuarios (Enter acepta lo detectado).
5. El instalador crea los certificados, abre el firewall **solo para la red local**, hace que Comandia arranque solo al encender el equipo (aunque nadie inicie sesión) y lo inicia.
6. En el servidor, ejecuta `servidor\instalar-certificado-aqui.bat` y abre `https://localhost`.
7. Entra con `luis@miempresa.hn` / `comandia123`, **cambia la clave**, crea los usuarios (Configuración › Usuarios), carga el CAI y activa la licencia.

> En el servidor **no uses `Comandia.exe`** (es para un solo equipo).

## Conectar cada computadora (una vez, ~2 minutos)
1. Abre el navegador y entra a `http://NOMBRE-O-IP-DEL-SERVIDOR` (por ejemplo `http://comandia`).
2. Pulsa **Instalar certificado (Windows)**, ejecuta el archivo y acepta el aviso de administrador. Cierra y abre el navegador.
3. Pulsa **Abrir Comandia**. Guarda `https://comandia` como favorito, o copia `servidor\clientes\Comandia.url` al escritorio.
4. Opcional: en Chrome/Edge, menú › **Instalar Comandia** para tenerlo como aplicación.

*Firefox:* importa `ca.crt` en Ajustes › Certificados › Autoridades (la misma página lo explica).

## Día a día
| Quiero… | Hago… |
|---|---|
| Ver si está funcionando | `servidor\estado-servidor.bat` (estado, usuarios conectados y últimas líneas del registro) |
| Detener / iniciar | `servidor\detener-servidor.bat` / `servidor\iniciar-servidor.bat` |
| Actualizar a una versión nueva | Descomprime el zip nuevo **encima** de `C:\Comandia` y ejecuta `servidor\actualizar-servidor.bat` (respalda y actualiza la base). Los usuarios pulsan Ctrl+F5 |
| Cambió la IP o el nombre | Edita `nombres=` en `servidor.conf` y ejecuta `servidor\renovar-certificado.bat` (los clientes **no** repiten nada) |
| Quitarlo | `servidor\desinstalar-servidor.bat` (no borra datos) |

El registro está en `logs\servidor.log`. Si Comandia se cae, se reinicia solo en 15 segundos.

## Respaldos (importante)
Configuración › Respaldos: elige una carpeta en **otro disco** (o una unidad de red) y copia esa carpeta a una USB o a la nube cada semana. Un respaldo en el mismo disco no protege contra la falla del disco.

## Seguridad
- El firewall solo acepta conexiones de la **red local**; no abras estos puertos hacia internet.
- Todo viaja cifrado (HTTPS). La llave `certs\ca.key` **no se copia ni se comparte**: con ella se pueden emitir certificados falsos.
- Una clave por persona, y desactiva (no borres) a quien deje de trabajar.
- **Licencia:** es una por servidor (un código de instalación), sin límite de usuarios conectados.

## Problemas comunes
- **«No se puede conectar»**: ejecuta `estado-servidor.bat`; revisa que MySQL esté iniciado y que el servidor y la PC estén en la misma red.
- **El puerto 443 está ocupado** (IIS, Skype, otro programa): en `servidor.conf` pon `puerto_https=8443`, ejecuta `renovar-certificado.bat` y entra a `https://servidor:8443`.
- **El navegador avisa que el sitio no es seguro**: falta instalar el certificado en esa PC (paso 2 de «Conectar»).
- **Cambió la IP y nadie entra**: reserva la IP en el router y usa `renovar-certificado.bat` si cambió.
- **Después de un corte de luz**: al encender el equipo Comandia inicia solo (espera ~1 minuto a MySQL).
