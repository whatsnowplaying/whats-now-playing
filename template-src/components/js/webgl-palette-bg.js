// Shared infrastructure for palette-driven WebGL dynamic backgrounds.
// Provides WNPPaletteBg.GLSL (shared GLSL uniforms + palette helpers) and
// WNPPaletteBg.init(fragSrc) which wires up the canvas, render loop, and
// window.updateDisplay.  Each background template JS file just defines its
// own FRAG_SRC = WNPPaletteBg.GLSL + 'void main() { ... }' and calls init().
'use strict';

window.WNPPaletteBg = (function () {

    // ── Shared GLSL prefix ────────────────────────────────────────────────────
    // Included verbatim at the top of every background shader.  Provides the
    // standard uniforms and two palette-sampling helpers that walk through
    // 6 color stops.  GLSL ES 1.0 forbids non-constant uniform array indices,
    // so sampleA/sampleB use if/else chains instead of dynamic indexing.

    const GLSL = `
        precision mediump float;
        varying vec2  v_uv;
        uniform float u_time;
        uniform float u_ar;       // width/height aspect ratio
        uniform float u_blend;    // 0 = palette A, 1 = palette B
        uniform vec3  u_palette_a[6];
        uniform vec3  u_palette_b[6];

        vec3 sampleA(float t) {
            t = fract(t) * 5.0;
            float f = fract(t);
            if (t < 1.0) return mix(u_palette_a[0], u_palette_a[1], f);
            if (t < 2.0) return mix(u_palette_a[1], u_palette_a[2], f);
            if (t < 3.0) return mix(u_palette_a[2], u_palette_a[3], f);
            if (t < 4.0) return mix(u_palette_a[3], u_palette_a[4], f);
                         return mix(u_palette_a[4], u_palette_a[5], f);
        }

        vec3 sampleB(float t) {
            t = fract(t) * 5.0;
            float f = fract(t);
            if (t < 1.0) return mix(u_palette_b[0], u_palette_b[1], f);
            if (t < 2.0) return mix(u_palette_b[1], u_palette_b[2], f);
            if (t < 3.0) return mix(u_palette_b[2], u_palette_b[3], f);
            if (t < 4.0) return mix(u_palette_b[3], u_palette_b[4], f);
                         return mix(u_palette_b[4], u_palette_b[5], f);
        }
    `;

    const VERT_SRC = `
        attribute vec2 a_pos;
        varying   vec2 v_uv;
        void main() {
            v_uv        = a_pos * 0.5 + 0.5;
            gl_Position = vec4(a_pos, 0.0, 1.0);
        }
    `;

    // Neutral cool-grey shown before the first track arrives.
    const NEUTRAL = [
        0.22, 0.22, 0.28,
        0.18, 0.18, 0.24,
        0.25, 0.25, 0.30,
        0.20, 0.20, 0.26,
        0.16, 0.16, 0.22,
        0.23, 0.23, 0.29,
    ];

    // ── Public API ────────────────────────────────────────────────────────────

    function init(fragSrc) {
        const canvas = document.getElementById('bgCanvas');
        canvas.width  = window.innerWidth  || 1920;
        canvas.height = window.innerHeight || 1080;

        const gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: false });
        if (!gl) {
            console.error('WebGL not available');
            window.updateDisplay = function () {};
            return;
        }

        gl.enable(gl.BLEND);
        gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

        const prog = WNPWebGL.compileProgram(gl, VERT_SRC, fragSrc);
        WNPWebGL.fullscreenQuad(gl, prog);

        const uTime     = gl.getUniformLocation(prog, 'u_time');
        const uAr       = gl.getUniformLocation(prog, 'u_ar');
        const uBlend    = gl.getUniformLocation(prog, 'u_blend');
        const uPaletteA = gl.getUniformLocation(prog, 'u_palette_a[0]');
        const uPaletteB = gl.getUniformLocation(prog, 'u_palette_b[0]');

        let paletteA  = Float32Array.from(NEUTRAL);
        let paletteB  = Float32Array.from(NEUTRAL);
        let blendVal  = 0;

        const TRANSITION_MS = 2000;
        let   transStart    = null;

        function parsePalette(str) {
            if (!str) return null;
            const valid = str.split(',').map(s => s.trim().replace('#', '')).filter(h => /^[0-9a-fA-F]{6}$/.test(h));
            if (!valid.length) return null;
            const out = new Float32Array(18);
            for (let i = 0; i < 6; i++) {
                const h = valid[i % valid.length];
                out[i*3]   = parseInt(h.slice(0, 2), 16) / 255;
                out[i*3+1] = parseInt(h.slice(2, 4), 16) / 255;
                out[i*3+2] = parseInt(h.slice(4, 6), 16) / 255;
            }
            return out;
        }

        function currentBlendedPalette() {
            const out = new Float32Array(18);
            for (let i = 0; i < 18; i++) {
                out[i] = paletteA[i] * (1 - blendVal) + paletteB[i] * blendVal;
            }
            return out;
        }

        const t0 = performance.now();

        function frame(now) {
            if (transStart !== null) {
                blendVal = Math.min(1, (now - transStart) / TRANSITION_MS);
                if (blendVal >= 1) {
                    paletteA   = Float32Array.from(paletteB);
                    blendVal   = 0;
                    transStart = null;
                }
            }

            const t  = (now - t0) / 1000;
            const ar = canvas.width / canvas.height;

            gl.viewport(0, 0, canvas.width, canvas.height);
            gl.clearColor(0, 0, 0, 0);
            gl.clear(gl.COLOR_BUFFER_BIT);

            gl.uniform1f(uTime,  t);
            gl.uniform1f(uAr,    ar);
            gl.uniform1f(uBlend, blendVal);
            gl.uniform3fv(uPaletteA, paletteA);
            gl.uniform3fv(uPaletteB, paletteB);

            gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
            requestAnimationFrame(frame);
        }
        requestAnimationFrame(frame);

        window.updateDisplay = function (metadata) {
            if (!metadata || !metadata.title) return;

            // cover_palette_lighting uses a vibrant filter — monochromatic covers
            // (e.g. a solid-blue sleeve) yield only 1-2 colors, leaving the
            // background flat.  Fall back to the richer display palette in that case.
            let raw = metadata.cover_palette_lighting;
            const colorCount = raw ? raw.split(',').filter(Boolean).length : 0;
            if (colorCount < 3) {
                raw = metadata.cover_palette || raw;
            }

            const next = parsePalette(raw);
            if (!next) return;

            paletteA   = currentBlendedPalette();
            paletteB   = next;
            blendVal   = 0;
            transStart = performance.now();
        };
    }

    return { GLSL, init };
}());
