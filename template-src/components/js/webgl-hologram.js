// WebGL Hologram (scanline + glitch) Display
'use strict';

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
            col         += band * vec3(0.0, 0.6, 0.45) * 0.9;

            // Horizontal edge fringe (chromatic-aberration feel on left border)
            float edgeX  = smoothstep(0.0, 0.04, uv.x);
            col         += (1.0 - edgeX) * vec3(0.0, 0.8, 0.5) * 0.4;

            // Top/bottom soft vignette
            float vy     = uv.y * (1.0 - uv.y) * 4.0;
            col         *= clamp(vy, 0.0, 1.0);

            // Glitch colour burst
            if (u_glitch > 0.01) {
                float gr  = rand(vec2(floor(uv.y * 40.0), floor(u_time * 25.0)));
                if (gr > (1.0 - u_glitch * 0.4)) {
                    col  += vec3(0.0, 0.4, 0.3) * u_glitch * 0.5;
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

        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
        requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);

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
            targetActive = 0;
            card.classList.remove('visible');
            return;
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
    };
}());
