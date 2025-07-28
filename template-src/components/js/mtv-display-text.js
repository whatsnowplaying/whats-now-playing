// MTV Style Display - Text Only
function updateDisplay(metadata) {
    if (metadata.title) {
        $("#title").html('"' + metadata.title + '"');
        $("#artist").html(metadata.artist);
        $("#album").html(metadata.album);
        $("#label").html(metadata.label);
    } else {
        $("#title").html('');
        $("#artist").html('');
        $("#album").html('');
        $("#label").html('');
    }
}