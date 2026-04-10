// WebGL Wave-Edge Panel
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

    // Wavy top boundary: two overlapping sine waves define the panel edge.
    // Below the wave = panel; above = transparent stream shows through.
    // A soft glow line traces the wave edge itself.
    const FRAG_SRC = `
        precision mediump float;
        varying vec2  v_uv;
        uniform float u_time;
        uniform float u_active;

        void main() {
            // Wave boundary: two sines at different frequencies and speeds
            float wave = 0.72
                + 0.10 * sin(v_uv.x * 6.5  + u_time * 1.1)
                + 0.05 * sin(v_uv.x * 14.0 - u_time * 0.7);

            // Signed distance from wave (positive = below / inside panel)
            float d = wave - v_uv.y;

            // Panel fill: opaque below wave, fade out toward top edge
            float fill  = smoothstep(-0.015, 0.015, d);

            // Dark navy panel colour with subtle left-to-right gradient
            vec3  col   = mix(vec3(0.03, 0.05, 0.14), vec3(0.06, 0.08, 0.18), v_uv.x);

            // Glow line tracing the wave edge
            float glow  = exp(-abs(d) * 80.0) * 0.9;
            col        += glow * vec3(0.15, 0.55, 1.0);

            gl_FragColor = vec4(col, (fill * 0.88 + glow * 0.6) * u_active);
        }
    `;

    const prog = WNPWebGL.compileProgram(gl, VERT_SRC, FRAG_SRC);
    WNPWebGL.fullscreenQuad(gl, prog);

    const uTime   = gl.getUniformLocation(prog, 'u_time');
    const uActive = gl.getUniformLocation(prog, 'u_active');

    let active       = 0;
    let targetActive = 0;
    const t0         = performance.now();

    function frame() {
        const t = (performance.now() - t0) / 1000;
        active += (targetActive - active) * 0.04;

        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);

        gl.uniform1f(uTime,   t);
        gl.uniform1f(uActive, active);

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

        document.getElementById('track-artist').textContent = metadata.artist || '';
        document.getElementById('track-title').textContent  =
            '\u201c' + metadata.title + '\u201d';
        card.classList.add('visible');
        targetActive = 1;
    };
}());
