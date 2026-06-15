// WebGL Wave-Edge Panel
'use strict';

function _wnpAccentVec3() {
    const raw = (getComputedStyle(document.documentElement)
                     .getPropertyValue('--wnp-accent-color') || '#2680ff').trim();
    const m = raw.match(/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
    if (m) return [parseInt(m[1], 16) / 255, parseInt(m[2], 16) / 255, parseInt(m[3], 16) / 255];
    const r = raw.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
    if (r) return [parseInt(r[1]) / 255, parseInt(r[2]) / 255, parseInt(r[3]) / 255];
    return [0.15, 0.55, 1.0];
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

    // Wavy top boundary: two overlapping sine waves define the panel edge.
    // Below the wave = panel; above = transparent stream shows through.
    // A soft glow line traces the wave edge itself.
    const FRAG_SRC = `
        precision mediump float;
        varying vec2  v_uv;
        uniform float u_time;
        uniform float u_active;
        uniform vec3  u_accent;

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
            col        += glow * u_accent;

            gl_FragColor = vec4(col, (fill * 0.88 + glow * 0.6) * u_active);
        }
    `;

    const prog = WNPWebGL.compileProgram(gl, VERT_SRC, FRAG_SRC);
    WNPWebGL.fullscreenQuad(gl, prog);

    const uTime   = gl.getUniformLocation(prog, 'u_time');
    const uActive = gl.getUniformLocation(prog, 'u_active');
    const uAccent = gl.getUniformLocation(prog, 'u_accent');

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

        const coverImg = document.getElementById('cover-image');
        if (metadata.coverimagebase64) {
            coverImg.src = 'data:image/jpeg;base64,' + metadata.coverimagebase64;
        } else if (metadata.artistthumbnailbase64) {
            coverImg.src = 'data:image/jpeg;base64,' + metadata.artistthumbnailbase64;
        } else {
            coverImg.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
        }

        document.getElementById('track-artist').textContent = metadata.artist || '';
        document.getElementById('track-title').textContent  =
            '\u201c' + metadata.title + '\u201d';
        document.getElementById('track-album').textContent  = metadata.album || '';
        card.classList.add('visible');
        targetActive = 1;
    };
}());
