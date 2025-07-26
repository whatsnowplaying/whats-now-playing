// Single Image Display (for cover, artistlogo, etc.)
function updateDisplay(metadata) {
    const img = document.createElement("img")

    // Determine which image field to use based on template type
    const imageField = getImageField();
    img.src = 'data:image/png;base64,' + metadata[imageField + 'base64'];

    if (metadata.title || metadata.artist) {
        $("#image-display").html(img);
    } else {
        $("#image-display").html('');
    }
}

// This will be customized per template
function getImageField() {
    return 'coverimage'; // Default, overridden by specific templates
}