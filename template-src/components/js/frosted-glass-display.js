// Frosted Glass Display
'use strict';

window.updateDisplay = function (metadata) {
    const card = document.getElementById('card');
    if (!metadata || !metadata.title) {
        document.getElementById('track-artist').textContent = '';
        document.getElementById('track-title').textContent  = '';
        card.classList.remove('visible');
        return;
    }

    document.getElementById('track-artist').textContent = metadata.artist || '';
    document.getElementById('track-title').textContent  =
        '\u201c' + metadata.title + '\u201d';
    card.classList.add('visible');
};
