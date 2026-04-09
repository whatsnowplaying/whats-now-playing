// Artist Fanart Slideshow
// Fetches multiple fanart images via the images WS and slides through them.
'use strict';

(function () {
    const slideA   = document.getElementById('slide-a');
    const slideB   = document.getElementById('slide-b');
    const INTERVAL = 8000;   // ms between slides
    const FETCH_N  = 20;     // how many fanart images to request per artist

    let images       = [];   // base64 data URLs for current artist
    let currentIdx   = 0;
    let currentSlide = slideA;
    let nextSlide    = slideB;
    let slideTimer   = null;
    let currentArtist = null;
    let seenB64      = [];

    // ── Images WebSocket ──────────────────────────────────────────────────
    let imagesWs = null;

    function connectImagesWs() {
        const url = 'ws://{{hostip}}:{{httpport}}/v1/images/ws';
        imagesWs = new WebSocket(url);

        imagesWs.onopen = () => {
            imagesWs.send(JSON.stringify({ type: 'hello' }));
        };

        imagesWs.onmessage = (evt) => {
            const d = JSON.parse(evt.data);
            if (d.type === 'image_data' && d.category === 'fanart') {
                if (seenB64.includes(d.image_data)) return;
                seenB64.push(d.image_data);
                const dataUrl = 'data:image/png;base64,' + d.image_data;
                images.push(dataUrl);
                // Show the first image as soon as it arrives
                if (images.length === 1) showSlide(images[0]);
                // Start cycling as soon as a second image is available
                if (images.length === 2 && slideTimer === null) startTimer();
            }
        };

        imagesWs.onclose = () => setTimeout(connectImagesWs, 3000);
        imagesWs.onerror = () => {};
    }

    function _sendFanartRequests(artist, count) {
        for (let i = 0; i < count; i++) {
            setTimeout(() => {
                if (imagesWs && imagesWs.readyState === WebSocket.OPEN && artist === currentArtist) {
                    imagesWs.send(JSON.stringify({
                        type: 'get_images',
                        data_type: 'artist',
                        category: 'fanart',
                        parameters: { artist },
                    }));
                }
            }, i * 100);
        }
    }

    function fetchFanart(artist) {
        if (!imagesWs || imagesWs.readyState !== WebSocket.OPEN) return;
        seenB64    = [];
        images     = [];
        currentIdx = 0;
        stopTimer();
        _sendFanartRequests(artist, FETCH_N);
        // Start cycling after the first wave has had time to arrive
        setTimeout(startTimer, FETCH_N * 100 + 500);
        // Keep retrying for missing images while downloads may still be arriving
        setTimeout(() => _retryMissingFanart(artist, 0), 15000);
    }

    function _retryMissingFanart(artist, attempt) {
        if (artist !== currentArtist) return;        // artist changed, abandon
        if (images.length >= FETCH_N) return;        // already have enough
        const missing = FETCH_N - images.length;
        _sendFanartRequests(artist, missing);
        if (attempt < 7) {  // up to ~2 minutes of retries
            setTimeout(() => _retryMissingFanart(artist, attempt + 1), 15000);
        }
    }

    // ── Slide mechanics ───────────────────────────────────────────────────
    function showSlide(dataUrl) {
        nextSlide.style.backgroundImage = `url('${dataUrl}')`;
        // Force reflow so transition fires
        nextSlide.getBoundingClientRect();
        nextSlide.classList.add('entering');
        const leaving = currentSlide;
        const entering = nextSlide;
        // Only animate the leaving slide if it actually has an image to show
        if (leaving.style.backgroundImage) {
            leaving.classList.add('leaving');
        }
        entering.addEventListener('transitionend', function handler() {
            entering.removeEventListener('transitionend', handler);
            leaving.classList.remove('leaving', 'entering');  // fully reset to off-screen
            leaving.style.backgroundImage = '';
        }, { once: true });
        // Swap current / next references
        currentSlide = entering;
        nextSlide    = leaving;
    }

    function advance() {
        if (images.length <= 1) return;
        currentIdx = (currentIdx + 1) % images.length;
        showSlide(images[currentIdx]);
    }

    function startTimer() {
        stopTimer();
        if (images.length > 1) {
            slideTimer = setInterval(advance, INTERVAL);
        }
    }

    function stopTimer() {
        if (slideTimer !== null) {
            clearInterval(slideTimer);
            slideTimer = null;
        }
    }

    // ── updateDisplay ─────────────────────────────────────────────────────
    window.updateDisplay = function (metadata) {
        if (!metadata || !metadata.artist) {
            stopTimer();
            return;
        }
        if (metadata.artist === currentArtist) return;
        currentArtist = metadata.artist;
        fetchFanart(metadata.artist);
    };

    connectImagesWs();
}());
