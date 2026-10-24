<?php
// Copiar como /home/herryavc/nico_config.php (fuera de public_html) y completar.
// No subir este archivo con valores reales al repo.
return array(
    'db_host' => 'localhost',
    'db_name' => 'herryavc_sgi',            // la base del SGI en vivo
    'db_user' => 'herryavc_nico_ro',        // usuario de solo lectura (SELECT)
    'db_password' => '',
    'token' => '',                           // el mismo valor que CRM_STATUS_TOKEN en Vercel
);
