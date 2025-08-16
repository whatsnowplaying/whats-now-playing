// Conditional Fanart Display (shows fanart for audio, transparent for video)
function updateDisplay(metadata) {
    // Clear display initially
    $("#image-display").html('');
    
    // Only show if we have track metadata
    if (!metadata.title && !metadata.artist) {
        return;
    }
    
    // Check if this is a video file
    const hasVideo = metadata.has_video === true || metadata.has_video === "true";
    
    if (hasVideo) {
        // For video files, show transparent 1x1 pixel PNG
        const transparentImg = document.createElement("img");
        transparentImg.src = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';
        transparentImg.style.width = '100%';
        transparentImg.style.height = '100%';
        transparentImg.style.opacity = '0';
        $("#image-display").html(transparentImg);
    } else {
        // For audio files, show artist fanart if available
        if (metadata.artistfanartbase64) {
            const fanartImg = document.createElement("img");
            fanartImg.src = 'data:image/png;base64,' + metadata.artistfanartbase64;
            $("#image-display").html(fanartImg);
        }
    }
}

// Helper function for compatibility with existing template system
function getImageField() {
    return 'artistfanart'; // This template primarily uses artist fanart
}