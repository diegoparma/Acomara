<?php
/**
 * Consulta de cliente para Nico.
 *
 * Recibe un teléfono o un mail y responde si la persona está en el SGI,
 * cuántas consultas tiene y la fecha de la última. No devuelve ningún otro dato.
 *
 * POST con header "X-Nico-Token" y cuerpo JSON {"phone": "...", "email": "..."}.
 * Compatible con PHP 5.6 en adelante (sgi.aconcaguaone.com corre 5.6).
 *
 * Las credenciales y el token van en un archivo fuera de la carpeta pública:
 * ver nico_config.example.php y README.md.
 */

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function responder($codigo, $datos)
{
    http_response_code($codigo);
    echo json_encode($datos);
    exit;
}

$config_path = getenv('HOME') ? getenv('HOME') . '/nico_config.php' : '/home/herryavc/nico_config.php';
if (!is_readable($config_path)) {
    responder(500, array('error' => 'config'));
}
$config = require $config_path;

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    responder(405, array('error' => 'method'));
}

$token = isset($_SERVER['HTTP_X_NICO_TOKEN']) ? $_SERVER['HTTP_X_NICO_TOKEN'] : '';
if ($token === '' || !hash_equals(hash('sha256', $config['token']), hash('sha256', $token))) {
    responder(401, array('error' => 'token'));
}

$entrada = json_decode(file_get_contents('php://input'), true);
if (!is_array($entrada)) {
    responder(400, array('error' => 'json'));
}

$phone = isset($entrada['phone']) ? trim((string) $entrada['phone']) : '';
$email = isset($entrada['email']) ? strtolower(trim((string) $entrada['email'])) : '';

// Un teléfono corto con LIKE devolvería cualquier cliente: se exigen 8 dígitos.
$phone_digits = preg_replace('/\D/', '', $phone);
if (strlen($phone_digits) < 8) {
    $phone = '';
}
if ($email !== '' && !filter_var($email, FILTER_VALIDATE_EMAIL)) {
    $email = '';
}
if ($phone === '' && $email === '') {
    responder(400, array('error' => 'input'));
}

mysqli_report(MYSQLI_REPORT_OFF);
$db = new mysqli($config['db_host'], $config['db_user'], $config['db_password'], $config['db_name']);
if ($db->connect_errno) {
    responder(503, array('error' => 'db'));
}
$db->set_charset('utf8');

$cliente = null;
$buscado_por = null;

if ($phone !== '') {
    $like = '%' . $phone . '%';
    $st = $db->prepare('SELECT idCliente, nombre, apellido FROM cliente WHERE (telefono = ? OR telefono LIKE ?) AND deleted IS NULL LIMIT 1');
    $st->bind_param('ss', $phone, $like);
    $st->execute();
    $st->bind_result($id, $nombre, $apellido);
    if ($st->fetch()) {
        $cliente = array('id' => $id, 'nombre' => trim($nombre . ' ' . $apellido));
        $buscado_por = 'phone';
    }
    $st->close();
}

if ($cliente === null && $email !== '') {
    $st = $db->prepare('SELECT idCliente, nombre, apellido FROM cliente WHERE (LOWER(eMail) = ? OR LOWER(eMail2) = ?) AND deleted IS NULL LIMIT 1');
    $st->bind_param('ss', $email, $email);
    $st->execute();
    $st->bind_result($id, $nombre, $apellido);
    if ($st->fetch()) {
        $cliente = array('id' => $id, 'nombre' => trim($nombre . ' ' . $apellido));
        $buscado_por = 'email';
    }
    $st->close();
}

if ($cliente === null) {
    $db->close();
    responder(200, array('found' => false));
}

$st = $db->prepare('SELECT COUNT(*), MAX(fecha) FROM consulta WHERE idCliente = ? AND deleted IS NULL');
$st->bind_param('i', $cliente['id']);
$st->execute();
$st->bind_result($cantidad, $ultima);
$st->fetch();
$st->close();
$db->close();

responder(200, array(
    'found' => true,
    'client_id' => (int) $cliente['id'],
    'client_name' => $cliente['nombre'],
    'consultation_count' => (int) $cantidad,
    'last_consultation_date' => $ultima ? (string) $ultima : null,
    'search_by' => $buscado_por,
));
