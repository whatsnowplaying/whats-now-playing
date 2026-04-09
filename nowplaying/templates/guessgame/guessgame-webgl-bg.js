// guessgame-webgl-bg.js
// Shared WebGL animated background for Guess Game overlays.
// Reads canvas dimensions from the DOM so it works for both
// guessgame-webgl.htm (800×500) and guessgame-leaderboard-webgl.htm (550×700).
'use strict';

(function initBG() {
    const canvas = document.getElementById('bgCanvas');
    const gl = canvas.getContext('webgl', { alpha: false });
    if (!gl) { canvas.style.background = '#010108'; return; }

    const vert = `
        attribute vec2 a_pos;
        void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }
    `;

    const frag = `
        precision mediump float;
        uniform float u_t;
        uniform vec2  u_res;

        float grid(vec2 uv, float sz, float lw) {
            vec2 g = fract(uv * sz);
            return clamp(
                step(1.0 - lw, g.x) + step(1.0 - lw, g.y),
                0.0, 1.0
            );
        }

        void main() {
            vec2 uv = gl_FragCoord.xy / u_res;

            vec3 col = mix(vec3(0.02, 0.01, 0.06), vec3(0.01, 0.02, 0.07), uv.y);

            float pulse = 0.35 + 0.2 * sin(u_t * 0.6);
            float g = grid(uv, 14.0, 0.025);
            col += g * vec3(0.0, 0.18, 0.42) * pulse;

            float sweep = fract(u_t * 0.12);
            float band  = smoothstep(0.025, 0.0, abs(uv.y - sweep));
            col += band * vec3(0.0, 0.35, 0.7) * 0.65;

            col *= 0.96 + 0.04 * step(0.5, fract(uv.y * 300.0));

            vec2 c = uv - 0.5;
            col  *= clamp(1.0 - dot(c, c) * 2.0, 0.0, 1.0);

            gl_FragColor = vec4(col, 1.0);
        }
    `;

    function makeShader(type, src) {
        const s = gl.createShader(type);
        gl.shaderSource(s, src);
        gl.compileShader(s);
        return s;
    }

    const prog = gl.createProgram();
    gl.attachShader(prog, makeShader(gl.VERTEX_SHADER,   vert));
    gl.attachShader(prog, makeShader(gl.FRAGMENT_SHADER, frag));
    gl.linkProgram(prog);
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER,
        new Float32Array([-1,-1, 1,-1, -1,1, 1,1]), gl.STATIC_DRAW);

    const aPos = gl.getAttribLocation(prog, 'a_pos');
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

    const uT   = gl.getUniformLocation(prog, 'u_t');
    const uRes = gl.getUniformLocation(prog, 'u_res');
    gl.uniform2f(uRes, canvas.width, canvas.height);

    const t0 = performance.now();
    (function frame() {
        gl.uniform1f(uT, (performance.now() - t0) / 1000);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
        requestAnimationFrame(frame);
    })();
}());
