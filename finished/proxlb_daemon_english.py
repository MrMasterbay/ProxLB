<?php
// login_2fa.php
session_start();
require_once 'db.php';
require_once 'functions.php';

if (!isset($_SESSION['2fa_code'])) {
    header("Location: login.php");
    exit;
}

if ($_SERVER["REQUEST_METHOD"] == "POST") {
    $inputCode = trim($_POST['code']);
    if ($inputCode == $_SESSION['2fa_code']) {
        $_SESSION['user_id'] = $_SESSION['user_id_temp'];
        $_SESSION['username'] = $_SESSION['username_temp'];
        unset($_SESSION['2fa_code'], $_SESSION['user_id_temp'], $_SESSION['username_temp']);
        header("Location: dashboard.php");
        exit;
    } else {
        $error = "Falscher 2FA-Code.";
    }
}
include 'header.php';
?>

<h2>2FA Verifizierung</h2>

<?php if(isset($error)): ?>
    <div class="alert alert-error"><?php echo $error; ?></div>
<?php endif; ?>

<form method="post" action="">
    <div class="form-group">
        <label>2FA-Code:</label>
        <input type="text" name="code" required>
    </div>
    <input type="submit" value="Verifizieren">
</form>

<?php include 'footer.php'; ?>
