// WebGL Hologram (scanline + glitch) Display
'use strict';

function _wnpAccentVec3() {
    const raw = (getComputedStyle(document.documentElement)
                     .getPropertyValue('--wnp-accent-color') || '#00ffb4').trim();
    const m = raw.match(/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
    if (m) return [parseInt(m[1], 16) / 255, parseInt(m[2], 16) / 255, parseInt(m[3], 16) / 255];
    const r = raw.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
    if (r) return [parseInt(r[1]) / 255, parseInt(r[2]) / 255, parseInt(r[3]) / 255];
    return [0.0, 1.0, 0.71];
}

(function () {
    const canvas = document.getElementById('bgCanvas');
    const gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: false });

    if (!gl) {
        console.error('WebGL not available');
        window.updateDisplay = function () {};
        return;
    }

    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    const VERT_SRC = `
        attribute vec2 a_pos;
        varying   vec2 v_uv;
        void main() {
            v_uv        = a_pos * 0.5 + 0.5;
            gl_Position = vec4(a_pos, 0.0, 1.0);
        }
    `;

    // Panel background with:
    //   - Dark base + teal tint
    //   - Horizontal scanlines
    //   - Sweep glow (top-to-bottom periodic scan)
    //   - Chromatic-aberration-style edge fringe
    //   - Glitch blocks on u_glitch pulse
    const FRAG_SRC = `
        precision mediump float;
        varying vec2  v_uv;
        uniform float u_time;
        uniform float u_active;
        uniform float u_glitch;
        uniform vec3  u_accent;

        float rand(vec2 co) {
            return fract(sin(dot(co, vec2(12.9898, 78.233))) * 43758.5453);
        }

        void main() {
            vec2 uv = v_uv;

            // Glitch: randomly offset horizontal slices
            if (u_glitch > 0.01) {
                float sliceY    = floor(uv.y * 24.0);
                float sliceRand = rand(vec2(sliceY, floor(u_time * 30.0)));
                if (sliceRand > (1.0 - u_glitch * 0.6)) {
                    uv.x += (rand(vec2(sliceY + 1.0, u_time)) - 0.5) * 0.06 * u_glitch;
                }
            }

            // Dark teal panel base
            vec3 col = mix(vec3(0.01, 0.05, 0.09), vec3(0.02, 0.09, 0.12), uv.y);

            // Scanlines: alternating bright/dark bands
            float scan   = 0.75 + 0.25 * step(0.5, fract(uv.y * 75.0));
            col         *= scan;

            // Periodic sweep glow (fast scan line moving top to bottom)
            float sweep  = fract(u_time * 0.4);
            float band   = smoothstep(0.03, 0.0, abs(uv.y - sweep));
            col         += band * u_accent * 0.9;

            // Horizontal edge fringe (chromatic-aberration feel on left border)
            float edgeX  = smoothstep(0.0, 0.04, uv.x);
            col         += (1.0 - edgeX) * u_accent * 0.4;

            // Top/bottom soft vignette
            float vy     = uv.y * (1.0 - uv.y) * 4.0;
            col         *= clamp(vy, 0.0, 1.0);

            // Glitch colour burst
            if (u_glitch > 0.01) {
                float gr  = rand(vec2(floor(uv.y * 40.0), floor(u_time * 25.0)));
                if (gr > (1.0 - u_glitch * 0.4)) {
                    col  += u_accent * 0.7 * u_glitch * 0.5;
                }
            }

            gl_FragColor = vec4(col, 0.88 * u_active);
        }
    `;

    const prog = WNPWebGL.compileProgram(gl, VERT_SRC, FRAG_SRC);
    WNPWebGL.fullscreenQuad(gl, prog);

    const uTime   = gl.getUniformLocation(prog, 'u_time');
    const uActive = gl.getUniformLocation(prog, 'u_active');
    const uGlitch = gl.getUniformLocation(prog, 'u_glitch');
    const uAccent = gl.getUniformLocation(prog, 'u_accent');

    // ── Animation state ──────────────────────────────────────────────────
    let active       = 0;
    let targetActive = 0;
    let glitch       = 0;
    const t0         = performance.now();

    function frame() {
        const t = (performance.now() - t0) / 1000;

        active += (targetActive - active) * 0.04;
        glitch *= 0.88;   // decay glitch pulse

        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);

        gl.uniform1f(uTime,   t);
        gl.uniform1f(uActive, active);
        gl.uniform1f(uGlitch, glitch);
        gl.uniform3fv(uAccent, _wnpAccentVec3());

        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
        rafId = requestAnimationFrame(frame);
    }
    let rafId = requestAnimationFrame(frame);

    window.addEventListener('pagehide', () => {
        cancelAnimationFrame(rafId);
        const ext = gl.getExtension('WEBGL_lose_context');
        if (ext) ext.loseContext();
    });

    // ── Text glitch-reveal helper ─────────────────────────────────────────
    const CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@#$%&';
    function glitchReveal(el, finalText, duration) {
        const len     = finalText.length;
        const steps   = Math.ceil(duration / 40);
        let   step    = 0;
        const timer   = setInterval(() => {
            step++;
            const revealed = Math.floor((step / steps) * len);
            let   display  = finalText.slice(0, revealed);
            if (revealed < len) {
                const scrambleLen = Math.min(4, len - revealed);
                for (let i = 0; i < scrambleLen; i++) {
                    display += CHARS[Math.floor(Math.random() * CHARS.length)];
                }
            }
            el.textContent = display;
            if (step >= steps) {
                el.textContent = finalText;
                clearInterval(timer);
            }
        }, 40);
    }

    // ── updateDisplay ─────────────────────────────────────────────────────
    window.updateDisplay = function (metadata) {
        const card = document.getElementById('card');
        if (!metadata || !metadata.title) {
            document.getElementById('track-artist').textContent = '';
            document.getElementById('track-title').textContent  = '';
            document.getElementById('track-album').textContent  = '';
            document.getElementById('track-label').textContent  = '';
            targetActive = 0;
            card.classList.remove('visible');
            return;
        }

        // Cover image (respects --wnp-cover-display via CSS)
        const coverImg = document.getElementById('cover-image');
        if (metadata.coverimagebase64) {
            coverImg.src = 'data:image/png;base64,' + metadata.coverimagebase64;
        } else if (metadata.artistthumbnailbase64) {
            coverImg.src = 'data:image/png;base64,' + metadata.artistthumbnailbase64;
        } else {
            coverImg.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
        }

        const isNew = document.getElementById('track-artist').textContent !== (metadata.artist || '');
        card.classList.add('visible');
        targetActive = 1;

        if (isNew) {
            glitch = 1.0;
            const artistEl = document.getElementById('track-artist');
            const titleEl  = document.getElementById('track-title');
            glitchReveal(artistEl, metadata.artist || '', 600);
            glitchReveal(titleEl,  '\u201c' + metadata.title + '\u201d', 800);
        }
        document.getElementById('track-album').textContent = metadata.album || '';
        document.getElementById('track-label').textContent = metadata.label  || '';
    };
}());
