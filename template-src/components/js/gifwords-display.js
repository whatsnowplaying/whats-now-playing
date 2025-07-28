// GIF Words Display
function updateDisplay(metadata) {
    const img = document.createElement("img");

    if (metadata.imagebase64) {
        console.log('here');
        img.src = 'data:image/gif;base64,' + metadata.imagebase64;
        $("#gifwordsartimg").html(img);
    } else {
        $("#gifwordsartimg").html('');
    }
}