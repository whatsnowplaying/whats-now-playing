// WebGL Vinyl Record Display
'use strict';

(function () {
    // ── WebGL init ──────────────────────────────────────────────────────
    const canvas = document.getElementById('vinylCanvas');
    const gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: false });

    if (!gl) {
        console.error('WebGL not available');
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

    const FRAG_SRC = `
        precision mediump float;
        varying   vec2      v_uv;
        uniform   sampler2D u_cover;
        uniform   float     u_rotation;
        uniform   float     u_alpha;
        uniform   float     u_hasCover;

        void main() {
            vec2  c    = v_uv - 0.5;
            float dist = length(c);

            if (dist > 0.5) discard;

            // Rotate texture UVs for outer vinyl area
            float cosR   = cos(u_rotation);
            float sinR   = sin(u_rotation);
            vec2  rotUV  = vec2(
                c.x * cosR - c.y * sinR,
                c.x * sinR + c.y * cosR
            ) * 0.5 + 0.5;

            // Unrotated UV for centre label (scaled to fill label circle)
            float labelR = 0.22;
            vec2  labUV  = clamp(c / (labelR * 2.0) + 0.5, 0.0, 1.0);

            vec4 rotCover = texture2D(u_cover, rotUV);
            vec4 labCover = texture2D(u_cover, labUV);

            // Vinyl groove rings: subtle concentric dark bands
            float groove  = 0.5 + 0.5 * sin(dist * 220.0);
            vec3  vinyl   = mix(vec3(0.04, 0.03, 0.06), vec3(0.13, 0.11, 0.16), groove);

            // Outer area: darken cover art and blend with vinyl grooves
            vec3  outerCol = (u_hasCover > 0.5)
                ? mix(vinyl, rotCover.rgb * 0.55, 0.45)
                : vinyl;

            // Centre label: full-brightness cover art (or plain dark disc)
            vec3  labCol   = (u_hasCover > 0.5) ? labCover.rgb : vec3(0.12, 0.10, 0.16);

            // Blend label / outer based on radius
            float inLabel  = 1.0 - smoothstep(labelR - 0.018, labelR + 0.018, dist);
            vec3  col      = mix(outerCol, labCol, inLabel);

            // Specular highlight (fixed light source, upper-left)
            vec2  norm     = normalize(c);
            float spec     = pow(max(0.0, dot(norm, normalize(vec2(-0.5, -0.7)))), 10.0);
            col           += spec * 0.18;

            // Centre hole
            float hole     = smoothstep(0.025, 0.038, dist);
            col           *= hole;

            // Edge anti-alias fade
            float edge     = smoothstep(0.5, 0.475, dist);

            gl_FragColor   = vec4(col, edge * hole * u_alpha);
        }
    `;

    function compileShader(type, src) {
        const s = gl.createShader(type);
        gl.shaderSource(s, src);
        gl.compileShader(s);
        if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
            console.error('Shader error:', gl.getShaderInfoLog(s));
        }
        return s;
    }

    const prog = gl.createProgram();
    gl.attachShader(prog, compileShader(gl.VERTEX_SHADER,   VERT_SRC));
    gl.attachShader(prog, compileShader(gl.FRAGMENT_SHADER, FRAG_SRC));
    gl.linkProgram(prog);
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER,
        new Float32Array([-1, -1,  1, -1,  -1, 1,  1, 1]), gl.STATIC_DRAW);

    const aPos = gl.getAttribLocation(prog, 'a_pos');
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

    const uRotation = gl.getUniformLocation(prog, 'u_rotation');
    const uAlpha    = gl.getUniformLocation(prog, 'u_alpha');
    const uHasCover = gl.getUniformLocation(prog, 'u_hasCover');
    const uCover    = gl.getUniformLocation(prog, 'u_cover');
    gl.uniform1i(uCover, 0);

    // ── Default 1×1 placeholder texture (avoids unbound-texture warnings) ──
    const placeholderTex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, placeholderTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0,
        gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([20, 16, 30, 255]));

    // ── Animation state ──────────────────────────────────────────────────
    let rotation    = 0;
    let spinSpeed   = 0;
    const TARGET_SPEED = 0.9;   // rad/s at normal play
    let coverTex    = placeholderTex;
    let nextTex     = null;
    let coverAlpha  = 0;
    let targetAlpha = 0;
    let hasCover    = 0;
    let pendingBase64 = null;

    function makeTexture(img) {
        const tex = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, tex);
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        return tex;
    }

    function loadCover(base64) {
        const img = new Image();
        img.onload = () => {
            nextTex = makeTexture(img);
        };
        img.src = 'data:image/png;base64,' + base64;
    }

    let lastTs = 0;
    function frame(ts) {
        const dt = Math.min((ts - lastTs) / 1000, 0.1);
        lastTs = ts;

        // Swap in new texture once loaded (fade is handled by coverAlpha)
        if (nextTex !== null) {
            if (coverTex !== placeholderTex) {
                gl.deleteTexture(coverTex);
            }
            coverTex  = nextTex;
            nextTex   = null;
            hasCover  = 1;
            // Brief spin-down then back up on track change
            spinSpeed = spinSpeed * 0.3;
        }

        // Load pending cover art after a brief hold to let spinSpeed settle
        if (pendingBase64) {
            loadCover(pendingBase64);
            pendingBase64 = null;
        }

        // Ramp spin speed toward target
        const speedTarget = (targetAlpha > 0) ? TARGET_SPEED : 0;
        spinSpeed += (speedTarget - spinSpeed) * Math.min(dt * 1.8, 1.0);
        rotation  += spinSpeed * dt;

        // Fade disc alpha
        coverAlpha += (targetAlpha - coverAlpha) * Math.min(dt * 2.5, 1.0);

        // Render
        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);

        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, coverTex);

        gl.uniform1f(uRotation, rotation);
        gl.uniform1f(uAlpha,    coverAlpha);
        gl.uniform1f(uHasCover, hasCover);

        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

        requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);

    // ── updateDisplay (called by metadata-streaming.js) ───────────────────
    window.updateDisplay = function (metadata) {
        const card = document.getElementById('card');
        if (!metadata || !metadata.title) {
            document.getElementById('track-artist').textContent = '';
            document.getElementById('track-title').textContent  = '';
            document.getElementById('track-album').textContent  = '';
            targetAlpha = 0;
            card.classList.remove('visible');
            return;
        }

        document.getElementById('track-artist').textContent =  metadata.artist || '';
        document.getElementById('track-title').textContent  = '\u201c' + metadata.title + '\u201d';
        document.getElementById('track-album').textContent  =  metadata.album  || '';
        card.classList.add('visible');

        targetAlpha = 1;
        if (metadata.coverimagebase64) {
            // Small delay so the fade-out completes before loading new texture
            pendingBase64 = metadata.coverimagebase64;
        }
    };
}());
