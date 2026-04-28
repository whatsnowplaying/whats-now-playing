// Matrix digital rain with character-scramble track reveal for What's Now Playing
'use strict';

(function () {
    // Shared character set: katakana + digits + Latin uppercase
    const CHARS =
        '\u30A2\u30A4\u30A6\u30A8\u30AA' +   // ア イ ウ エ オ
        '\u30AB\u30AD\u30AF\u30B1\u30B3' +   // カ キ ク ケ コ
        '\u30B5\u30B7\u30B9\u30BB\u30BD' +   // サ シ ス セ ソ
        '\u30BF\u30C1\u30C4\u30C6\u30C8' +   // タ チ ツ テ ト
        '\u30CA\u30CB\u30CC\u30CD\u30CE' +   // ナ ニ ヌ ネ ノ
        '\u30CF\u30D2\u30D5\u30D8\u30DB' +   // ハ ヒ フ へ ホ
        '\u30DE\u30DF\u30E0\u30E1\u30E2' +   // マ ミ ム メ モ
        '\u30E4\u30E6\u30E8' +               // ヤ ユ ヨ
        '\u30F2\u30F3' +                     // ヲ ン
        '0123456789' +
        'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

    function randomChar() {
        return CHARS[Math.floor(Math.random() * CHARS.length)];
    }

    // ---------------------------------------------------------------
    // Canvas rain background
    // ---------------------------------------------------------------
    const canvas = document.getElementById('matrix-canvas');
    const ctx = canvas.getContext('2d');

    if (!ctx) {
        console.error('Canvas 2D not available');
        window.updateDisplay = function () {};
        return;
    }

    const FONT_SIZE = 15;
    const FADE_ALPHA = 0.05;
    const BASE_HUE = 135;
    const BASE_SAT = 100;
    const BASE_LIT_MIN = 35;
    const BASE_LIT_RANGE = 30;

    let drops = [];

    function resize() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
        const columns = Math.floor(canvas.width / FONT_SIZE);
        const prev = drops.slice();
        drops = Array.from({ length: columns }, (_, i) =>
            i < prev.length ? prev[i] : Math.floor(Math.random() * (canvas.height / FONT_SIZE))
        );
    }

    function rainFrame() {
        ctx.fillStyle = `rgba(0, 0, 0, ${FADE_ALPHA})`;
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.font = `${FONT_SIZE}px monospace`;

        for (let col = 0; col < drops.length; col++) {
            const x = col * FONT_SIZE;
            const y = drops[col] * FONT_SIZE;

            if (Math.random() > 0.975) {
                ctx.fillStyle = '#ffffff';
            } else {
                const lit = BASE_LIT_MIN + Math.random() * BASE_LIT_RANGE;
                ctx.fillStyle = `hsl(${BASE_HUE}, ${BASE_SAT}%, ${lit}%)`;
            }

            ctx.fillText(randomChar(), x, y);

            if (y > canvas.height && Math.random() > 0.975) {
                drops[col] = 0;
            } else {
                drops[col]++;
            }
        }

        requestAnimationFrame(rainFrame);
    }

    // ---------------------------------------------------------------
    // Matrix decode: scramble chars then resolve to target text
    // ---------------------------------------------------------------
    const SCRAMBLE_INTERVAL = 40;   // ms between scramble updates
    const RESOLVE_DELAY = 80;       // ms between each character resolving

    function decodeText(element, targetText) {
        if (!targetText) {
            element.textContent = '';
            return;
        }

        const len = targetText.length;
        let resolved = 0;
        let frame = 0;

        // Clear any existing timer
        if (element._decodeTimer) {
            clearInterval(element._decodeTimer);
        }

        element._decodeTimer = setInterval(() => {
            // How many chars have resolved so far (one new char every RESOLVE_DELAY ms)
            resolved = Math.min(len, Math.floor(frame * SCRAMBLE_INTERVAL / RESOLVE_DELAY));

            element.textContent = targetText
                .split('')
                .map((ch, i) => {
                    if (ch === ' ') return '\u00A0';  // preserve spaces
                    if (i < resolved) return ch;      // already resolved
                    return randomChar();              // still scrambling
                })
                .join('');

            frame++;

            if (resolved >= len) {
                clearInterval(element._decodeTimer);
                element._decodeTimer = null;
                element.textContent = targetText;
            }
        }, SCRAMBLE_INTERVAL);
    }

    // ---------------------------------------------------------------
    // Track info overlay
    // ---------------------------------------------------------------
    const overlay = document.getElementById('track-overlay');
    const artistEl = document.getElementById('artist-text');
    const titleEl = document.getElementById('title-text');
    const albumEl = document.getElementById('album-text');

    let currentFingerprint = null;

    function updateOverlay(data) {
        const artist = data.artist || '';
        const title = data.title || '';
        const album = data.album || '';
        const fingerprint = `${artist}|${title}|${album}`;

        if (fingerprint === currentFingerprint) return;
        currentFingerprint = fingerprint;

        if (!artist && !title) {
            overlay.classList.add('hidden');
            return;
        }

        overlay.classList.remove('hidden');

        // Stagger the decode: artist first, then title, then album
        decodeText(artistEl, artist);
        setTimeout(() => decodeText(titleEl, title), artist.length * RESOLVE_DELAY * 0.5);
        setTimeout(() => decodeText(albumEl, album),
            (artist.length + title.length) * RESOLVE_DELAY * 0.5);
        albumEl.style.display = album ? '' : 'none';
    }

    // ---------------------------------------------------------------
    // Init
    // ---------------------------------------------------------------
    resize();
    window.addEventListener('resize', resize);
    requestAnimationFrame(rainFrame);

    window.updateDisplay = function (data) {
        updateOverlay(data);
    };
}());
