// MTV Style Display
function updateDisplay(metadata) {
    if (metadata.title) {
        const b64 = metadata.coverimagebase64 || metadata.artistthumbnailbase64;
        if (b64) {
            const img = document.createElement("img");
            img.src = 'data:image/png;base64,' + b64;
            img.className = "npimage";
            $("#cover").html(img);
        } else {
            $("#cover").html('');
        }
        $("#title").html('"' + metadata.title + '"');
        $("#artist").html(metadata.artist);
        $("#album").html(metadata.album);
        $("#label").html(metadata.label);
    } else {
        $("#cover").html('');
        $("#title").html('');
        $("#artist").html('');
        $("#album").html('');
        $("#label").html('');
    }
}