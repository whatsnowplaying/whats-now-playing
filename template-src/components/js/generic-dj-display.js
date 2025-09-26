/* Generic DJ Titlecard Display Logic */

function updateDisplay(data) {
    // Update cover image with artist thumbnail fallback
    const coverImg = document.getElementById('cover-image');
    if (data.coverimagebase64) {
        coverImg.src = 'data:image/jpeg;base64,' + data.coverimagebase64;
        coverImg.alt = 'Album cover for ' + (data.album || 'Unknown Album');
    } else if (data.artistthumbnailbase64) {
        // Fallback to artist thumbnail if no cover
        coverImg.src = 'data:image/jpeg;base64,' + data.artistthumbnailbase64;
        coverImg.alt = 'Artist thumbnail for ' + (data.artist || 'Unknown Artist');
    } else {
        // Keep the default transparent placeholder if neither is available
        coverImg.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
        coverImg.alt = 'No image available';
    }

    // Update artist name
    const artistElement = document.getElementById('artist-name');
    if (data.artist) {
        artistElement.textContent = data.artist;
        artistElement.style.display = 'block';
    } else {
        artistElement.style.display = 'none';
    }

    // Update track title (bold)
    const titleElement = document.getElementById('track-title');
    if (data.title) {
        titleElement.textContent = data.title;
        titleElement.style.display = 'block';
    } else {
        titleElement.style.display = 'none';
    }

    // Update record label (prioritize album over label)
    const labelElement = document.getElementById('record-label');
    if (data.album) {
        labelElement.textContent = data.album;
        labelElement.style.display = 'block';
    } else if (data.label) {
        // Fallback to label if no album
        labelElement.textContent = data.label;
        labelElement.style.display = 'block';
    } else {
        labelElement.style.display = 'none';
    }
}