// Particle Overlay — Canvas 2D (transparent background, particles over stream)
'use strict';

function _wnpAccentRGB() {
    const raw = (getComputedStyle(document.documentElement)
                     .getPropertyValue('--wnp-accent-color') || '#a0d2ff').trim();
    const m = raw.match(/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
    if (m) return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)];
    const r = raw.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
    if (r) return [parseInt(r[1]), parseInt(r[2]), parseInt(r[3])];
    return [160, 210, 255];
}

(function () {
    const canvas = document.getElementById('bgCanvas');
    const ctx    = canvas.getContext('2d');

    if (!ctx) {
        console.error('Canvas 2D not available');
        window.updateDisplay = function () {};
        return;
    }

    const W = canvas.width;
    const H = canvas.height;

    const N = 80;
    const particles = [];

    function makeParticle(startAtBottom) {
        return {
            x:     Math.random() * W,
            y:     startAtBottom ? H + Math.random() * 20 : Math.random() * H,
            vx:    (Math.random() - 0.5) * 0.4,
            vy:    -(Math.random() * 0.8 + 0.4),   // rise 0.4–1.2 px/frame
            r:     Math.random() * 2.5 + 1.5,       // radius 1.5–4px
            alpha: Math.random() * 0.55 + 0.2,
        };
    }

    for (let i = 0; i < N; i++) {
        particles.push(makeParticle(false));
    }

    let active      = false;
    let burstPending = false;

    function spawnBurst() {
        for (let i = 0; i < N; i++) {
            particles[i] = {
                x:     Math.random() * W,
                y:     H - Math.random() * 30,
                vx:    (Math.random() - 0.5) * 0.8,
                vy:    -(Math.random() * 1.8 + 0.8),
                r:     Math.random() * 4.0 + 2.0,
                alpha: Math.random() * 0.7 + 0.3,
            };
        }
    }

    function frame() {
        ctx.clearRect(0, 0, W, H);

        if (burstPending) {
            spawnBurst();
            burstPending = false;
        }

        if (active) {
            for (let i = 0; i < N; i++) {
                const p = particles[i];
                p.x += p.vx;
                p.y += p.vy;
                p.vx += (Math.random() - 0.5) * 0.06;   // slight horizontal wander

                // Fade out as particle approaches the top quarter
                if (p.y < H * 0.25) {
                    p.alpha -= 0.006;
                }

                // Recycle when off screen or faded out
                if (p.y < -10 || p.alpha <= 0) {
                    particles[i] = makeParticle(true);
                } else {
                    // Draw soft glowing circle
                    const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r * 2);
                    const [pr, pg, pb] = _wnpAccentRGB();
                    grad.addColorStop(0, `rgba(${pr}, ${pg}, ${pb}, ${p.alpha})`);
                    grad.addColorStop(0.5, `rgba(${pr}, ${pg}, ${pb}, ${p.alpha * 0.6})`);
                    grad.addColorStop(1, `rgba(${pr}, ${pg}, ${pb}, 0)`);
                    ctx.beginPath();
                    ctx.arc(p.x, p.y, p.r * 2, 0, Math.PI * 2);
                    ctx.fillStyle = grad;
                    ctx.fill();
                }
            }
        }

        rafId = requestAnimationFrame(frame);
    }
    let rafId = requestAnimationFrame(frame);

    window.addEventListener('pagehide', () => {
        cancelAnimationFrame(rafId);
    });

    // ── updateDisplay ─────────────────────────────────────────────────────
    window.updateDisplay = function (metadata) {
        const info = document.getElementById('track-info');
        if (!metadata || !metadata.title) {
            document.getElementById('track-artist').textContent = '';
            document.getElementById('track-title').textContent  = '';
            info.classList.remove('visible');
            active = false;
            return;
        }

        const coverImg = document.getElementById('cover-image');
        if (metadata.coverimagebase64) {
            coverImg.src = 'data:image/jpeg;base64,' + metadata.coverimagebase64;
        } else if (metadata.artistthumbnailbase64) {
            coverImg.src = 'data:image/jpeg;base64,' + metadata.artistthumbnailbase64;
        } else {
            coverImg.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
        }

        const isNew = document.getElementById('track-artist').textContent !== (metadata.artist || '');
        document.getElementById('track-artist').textContent = metadata.artist || '';
        document.getElementById('track-title').textContent  =
            '\u201c' + metadata.title + '\u201d';
        document.getElementById('track-album').textContent  = metadata.album || '';
        info.classList.add('visible');

        if (!active || isNew) {
            burstPending = true;
        }
        active = true;
    };
}());
