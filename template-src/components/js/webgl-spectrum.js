// WebGL Spectrum (fake EQ bars) Display
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

    // EQ bars: each column is a bar, height driven by overlapping sin waves.
    // u_beat fires a pulse (0→1→0) on each new track for an opening burst.
    const FRAG_SRC = `
        precision mediump float;
        varying vec2  v_uv;
        uniform float u_time;
        uniform float u_active;
        uniform float u_beat;

        float barHeight(float idx, float t) {
            float p = idx * 0.42 + t * 1.8;
            float h = 0.28
                + 0.22 * sin(p)
                + 0.13 * sin(p * 1.73 + 1.1)
                + 0.09 * sin(p * 2.41 + 2.3)
                + 0.05 * sin(p * 3.17 + 0.7);
            // Beat burst: push bars up briefly on new track
            h += u_beat * 0.5 * (0.5 + 0.5 * sin(idx * 0.7));
            return clamp(h, 0.04, 1.0);
        }

        void main() {
            float numBars = 56.0;
            float gapFrac = 0.28;      // fraction of each column that is gap

            float col      = v_uv.x * numBars;
            float barIdx   = floor(col);
            float barFrac  = fract(col);

            // Gap between bars
            if (barFrac > (1.0 - gapFrac)) {
                gl_FragColor = vec4(0.0);
                return;
            }

            float h = barHeight(barIdx, u_time) * u_active;

            // Above bar height: transparent
            if (v_uv.y > h) {
                gl_FragColor = vec4(0.0);
                return;
            }

            // Colour: cyan tip → blue base, beat adds brightness
            float t   = v_uv.y / h;
            vec3  tip = vec3(0.1, 1.0, 1.0) + u_beat * vec3(0.2, 0.0, 0.0);
            vec3  base= vec3(0.05, 0.35, 0.85);
            vec3  col3= mix(base, tip, t * t);

            // Mirror: bars are stronger in centre of the card
            float cx    = abs(v_uv.x - 0.5) * 2.0;
            float blend = 0.65 + 0.35 * (1.0 - cx * cx);

            // Fade the bottom 15% of each bar into the background
            float fade  = smoothstep(0.0, 0.15, v_uv.y);

            gl_FragColor = vec4(col3, (0.55 + 0.40 * t) * blend * fade);
        }
    `;

    const prog = WNPWebGL.compileProgram(gl, VERT_SRC, FRAG_SRC);
    WNPWebGL.fullscreenQuad(gl, prog);

    const uTime   = gl.getUniformLocation(prog, 'u_time');
    const uActive = gl.getUniformLocation(prog, 'u_active');
    const uBeat   = gl.getUniformLocation(prog, 'u_beat');

    // ── Animation state ──────────────────────────────────────────────────
    let active      = 0;
    let targetActive= 0;
    let beat        = 0;
    const t0        = performance.now();

    function frame() {
        const t  = (performance.now() - t0) / 1000;
        const dt = 0.016;

        active += (targetActive - active) * Math.min(dt * 2.0, 1.0);
        beat   *= 0.92;   // decay beat pulse

        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);

        gl.uniform1f(uTime,   t);
        gl.uniform1f(uActive, active);
        gl.uniform1f(uBeat,   beat);

        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
        requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);

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
        document.getElementById('track-artist').textContent = metadata.artist || '';
        document.getElementById('track-title').textContent  =
            '\u201c' + metadata.title + '\u201d';
        card.classList.add('visible');
        targetActive = 1;

        if (isNew) {
            beat = 1.0;   // trigger burst on new track
        }
    };
}());
