# Consulta de cliente para Nico (servidor del SGI)

Reemplaza la copia estática del 17/04/2026. Nico deja de conectarse a MySQL: le pregunta al SGI por HTTPS si quien escribe ya es cliente, y el SGI responde solo eso.

Respuesta: `{"found": false}` o `{"found": true, "client_id", "client_name", "consultation_count", "last_consultation_date", "search_by"}`.

## Instalación (cPanel de AconcaguaOne, cuenta `herryavc`)

1. **Base en vivo.** Confirmar cuál usa el SGI: `herryavc_aconcaguaone` o `herryavc_sgi` (ver `application/config/database.php` del SGI).
2. **Usuario de solo lectura.** En *MySQL Databases* crear `herryavc_nico_ro` con una contraseña nueva y darle **solo SELECT** sobre esa base.
3. **Token.** Generar uno largo, por ejemplo con `openssl rand -hex 32`.
4. **Config.** Subir `nico_config.example.php` como `/home/herryavc/nico_config.php`, fuera de `public_html`, y completarlo. Permisos 600.
5. **Endpoint.** Subir `nico_cliente_status.php` a la carpeta pública del SGI en vivo (`~/sgi` o `~/sgi_test`), de modo que quede en `https://sgi….aconcaguaone.com/nico_cliente_status.php`.
6. **Anti-bots.** El hosting pone una verificación ("One moment, please...") delante de las páginas. Probar que una llamada desde fuera del navegador llega al PHP:

   ```
   curl -s -X POST https://<sgi>/nico_cliente_status.php -H "X-Nico-Token: <token>" -H "Content-Type: application/json" -d '{"email":"no-existe@example.com"}'
   ```

   Tiene que responder `{"found":false}`. Si devuelve HTML, pedirle a Banahosting que excluya esa URL de Imunify360.
7. **Vercel.** Cargar `CRM_STATUS_URL` y `CRM_STATUS_TOKEN` en el proyecto de Nico. Con esas dos variables Nico usa el endpoint. Sin ellas sigue usando la copia de MySQL.
8. **Cerrar la copia.** Cuando funcione, borrar el usuario `acomara_ai` y las bases `acomara_ai_*` del servidor de Acomara, y quitar el acceso remoto a MySQL (Remote MySQL).
