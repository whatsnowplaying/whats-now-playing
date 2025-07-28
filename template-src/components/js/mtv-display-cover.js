// MTV Style Display with Cover Image
function updateDisplay(metadata) {
    const img = document.createElement("img")
    img.src = 'data:image/png;base64,' + metadata.coverimagebase64;
    img.className = "npimage"

    if (metadata.title) {
        $("#cover").html(img);
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