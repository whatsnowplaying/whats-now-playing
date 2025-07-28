// Basic Text Display
function updateDisplay(metadata) {
    if (metadata.title) {
        $("#title").html(metadata.title);
        $("#artist").html(metadata.artist || '');
    } else {
        $("#title").html('');
        $("#artist").html('');
    }
}