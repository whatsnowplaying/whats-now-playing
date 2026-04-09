// WebGL Fanart Cube Overlay
// Rotates a 3D cube textured with artist fanart (falls back to cover art)
'use strict';

(function () {
    const canvas = document.getElementById('cubeCanvas');
    const gl = canvas.getContext('webgl', { alpha: false });
    if (!gl) { console.error('WebGL not available'); return; }

    gl.enable(gl.DEPTH_TEST);
    gl.depthFunc(gl.LEQUAL);

    // ── Shaders ───────────────────────────────────────────────────────────
    const VERT_SRC = `
        attribute vec3 a_pos;
        attribute vec2 a_uv;
        attribute vec3 a_norm;
        uniform mat4 u_mvp;
        uniform mat4 u_model;
        varying vec2  v_uv;
        varying float v_light;
        void main() {
            v_uv = a_uv;
            gl_Position = u_mvp * vec4(a_pos, 1.0);
            vec3 worldNorm = normalize(mat3(u_model) * a_norm);
            vec3 lightDir  = normalize(vec3(0.6, 0.8, 1.0));
            float diffuse  = max(dot(worldNorm, lightDir), 0.0);
            v_light = 0.45 + 0.55 * diffuse;
        }
    `;
    const FRAG_SRC = `
        precision mediump float;
        varying vec2  v_uv;
        varying float v_light;
        uniform sampler2D u_tex;
        void main() {
            vec4 c = texture2D(u_tex, v_uv);
            gl_FragColor = vec4(c.rgb * v_light, c.a);
        }
    `;

    const prog = WNPWebGL.compileProgram(gl, VERT_SRC, FRAG_SRC);

    const aPos   = gl.getAttribLocation(prog, 'a_pos');
    const aUv    = gl.getAttribLocation(prog, 'a_uv');
    const aNorm  = gl.getAttribLocation(prog, 'a_norm');
    const uMvp   = gl.getUniformLocation(prog, 'u_mvp');
    const uModel = gl.getUniformLocation(prog, 'u_model');
    const uTex   = gl.getUniformLocation(prog, 'u_tex');

    // ── Cube geometry: 6 faces × 4 verts × (xyz uv nxyz) ─────────────────
    // Each face has CCW winding when viewed from outside; depth test handles rest.
    const S = 1.0;
    // prettier-ignore
    const VERTS = new Float32Array([
        // Front (z=+S)    xyz           uv    normal
        -S,-S, S,   0,0,   0, 0, 1,
         S,-S, S,   1,0,   0, 0, 1,
         S, S, S,   1,1,   0, 0, 1,
        -S, S, S,   0,1,   0, 0, 1,
        // Back (z=-S)
         S,-S,-S,   0,0,   0, 0,-1,
        -S,-S,-S,   1,0,   0, 0,-1,
        -S, S,-S,   1,1,   0, 0,-1,
         S, S,-S,   0,1,   0, 0,-1,
        // Top (y=+S)
        -S, S, S,   0,0,   0, 1, 0,
         S, S, S,   1,0,   0, 1, 0,
         S, S,-S,   1,1,   0, 1, 0,
        -S, S,-S,   0,1,   0, 1, 0,
        // Bottom (y=-S)
        -S,-S,-S,   0,0,   0,-1, 0,
         S,-S,-S,   1,0,   0,-1, 0,
         S,-S, S,   1,1,   0,-1, 0,
        -S,-S, S,   0,1,   0,-1, 0,
        // Right (x=+S)
         S,-S, S,   0,0,   1, 0, 0,
         S,-S,-S,   1,0,   1, 0, 0,
         S, S,-S,   1,1,   1, 0, 0,
         S, S, S,   0,1,   1, 0, 0,
        // Left (x=-S)
        -S,-S,-S,   0,0,  -1, 0, 0,
        -S,-S, S,   1,0,  -1, 0, 0,
        -S, S, S,   1,1,  -1, 0, 0,
        -S, S,-S,   0,1,  -1, 0, 0,
    ]);
    // prettier-ignore
    const INDICES = new Uint16Array([
         0, 1, 2,  0, 2, 3,   // Front
         4, 5, 6,  4, 6, 7,   // Back
         8, 9,10,  8,10,11,   // Top
        12,13,14, 12,14,15,   // Bottom
        16,17,18, 16,18,19,   // Right
        20,21,22, 20,22,23,   // Left
    ]);

    const vBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, vBuf);
    gl.bufferData(gl.ARRAY_BUFFER, VERTS, gl.STATIC_DRAW);

    const iBuf = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, iBuf);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, INDICES, gl.STATIC_DRAW);

    const F = Float32Array.BYTES_PER_ELEMENT;
    const STRIDE = 8 * F;  // xyz(3) + uv(2) + norm(3)

    function bindAttribs() {
        gl.enableVertexAttribArray(aPos);
        gl.vertexAttribPointer(aPos,  3, gl.FLOAT, false, STRIDE, 0);
        gl.enableVertexAttribArray(aUv);
        gl.vertexAttribPointer(aUv,   2, gl.FLOAT, false, STRIDE, 3 * F);
        gl.enableVertexAttribArray(aNorm);
        gl.vertexAttribPointer(aNorm, 3, gl.FLOAT, false, STRIDE, 5 * F);
    }

    // ── Matrix helpers (column-major, WebGL convention) ───────────────────
    function ident() {
        const m = new Float32Array(16);
        m[0] = m[5] = m[10] = m[15] = 1;
        return m;
    }

    function mul(a, b) {
        const m = new Float32Array(16);
        for (let c = 0; c < 4; c++) {
            for (let r = 0; r < 4; r++) {
                let s = 0;
                for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
                m[c * 4 + r] = s;
            }
        }
        return m;
    }

    function perspective(fov, asp, near, far) {
        const f = 1.0 / Math.tan(fov * 0.5);
        const m = new Float32Array(16);
        m[0]  = f / asp;
        m[5]  = f;
        m[10] = (far + near) / (near - far);
        m[11] = -1;
        m[14] = (2 * far * near) / (near - far);
        return m;
    }

    function rotX(a) {
        const m = ident();
        m[5]  =  Math.cos(a); m[9]  = -Math.sin(a);
        m[6]  =  Math.sin(a); m[10] =  Math.cos(a);
        return m;
    }

    function rotY(a) {
        const m = ident();
        m[0]  =  Math.cos(a); m[8]  =  Math.sin(a);
        m[2]  = -Math.sin(a); m[10] =  Math.cos(a);
        return m;
    }

    function transl(x, y, z) {
        const m = ident();
        m[12] = x; m[13] = y; m[14] = z;
        return m;
    }

    // ── Texture helpers ───────────────────────────────────────────────────
    function makeTexFromImg(img) {
        const tex = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, tex);
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
        // No mipmapping — album art and fanart are non-power-of-two sizes
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        return tex;
    }

    function loadFromB64(b64) {
        return new Promise(resolve => {
            const img = new Image();
            img.onload = () => resolve(makeTexFromImg(img));
            img.onerror = () => resolve(null);
            img.src = 'data:image/png;base64,' + b64;
        });
    }

    // One 1×1 grey placeholder so faces never render with a null texture
    function makePlaceholder() {
        const tex = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, tex);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE,
                      new Uint8Array([40, 40, 60, 255]));
        return tex;
    }

    const placeholder = makePlaceholder();

    // ── Texture state ─────────────────────────────────────────────────────
    const faceTex = new Array(6).fill(null);   // fanart per face
    let coverTex  = null;                      // current cover art fallback
    let seenB64   = [];                        // dedup buffer

    function texForFace(i) {
        if (i === 0) return coverTex || placeholder;        // face 0 = album cover
        return faceTex[i] || coverTex || placeholder;       // faces 1-5 = fanart, cover while loading
    }

    // ── Images WebSocket ──────────────────────────────────────────────────
    let imagesWs      = null;
    let fanartSlot    = 0;
    let fanartArtist  = null;   // used to cancel retries on artist change

    function connectImagesWs() {
        const url = 'ws://{{hostip}}:{{httpport}}/v1/images/ws';
        imagesWs = new WebSocket(url);

        imagesWs.onopen = () => {
            imagesWs.send(JSON.stringify({ type: 'hello' }));
        };

        imagesWs.onmessage = (evt) => {
            const d = JSON.parse(evt.data);
            if (d.type === 'image_data' && d.category === 'fanart') {
                if (seenB64.includes(d.image_data)) return;  // dedup
                seenB64.push(d.image_data);
                const slot = fanartSlot++;
                if (slot >= 1 && slot < 6) {
                    loadFromB64(d.image_data).then(tex => {
                        if (tex) faceTex[slot] = tex;
                    });
                }
            }
        };

        imagesWs.onclose = () => setTimeout(connectImagesWs, 3000);
        imagesWs.onerror = () => {};
    }

    function _sendFanartRequests(artist, count) {
        for (let i = 0; i < count; i++) {
            setTimeout(() => {
                if (imagesWs && imagesWs.readyState === WebSocket.OPEN && artist === fanartArtist) {
                    imagesWs.send(JSON.stringify({
                        type: 'get_images',
                        data_type: 'artist',
                        category: 'fanart',
                        parameters: { artist },
                    }));
                }
            }, i * 300);
        }
    }

    function fetchFanart(artist) {
        if (!imagesWs || imagesWs.readyState !== WebSocket.OPEN) return;
        seenB64      = [];
        fanartSlot   = 1;   // slot 0 is reserved for cover art
        fanartArtist = artist;
        faceTex.fill(null);
        _sendFanartRequests(artist, 5);
        // Keep retrying for empty slots every 15s while downloads may still be arriving
        setTimeout(() => _retryMissingFanart(artist, 0), 15000);
    }

    function _retryMissingFanart(artist, attempt) {
        if (artist !== fanartArtist) return;  // artist changed, abandon
        const missing = faceTex.slice(1).filter(t => t === null).length;
        if (missing === 0) return;            // all slots filled, done
        _sendFanartRequests(artist, missing);
        if (attempt < 7) {  // up to ~2 minutes of retries after initial fetch
            setTimeout(() => _retryMissingFanart(artist, attempt + 1), 15000);
        }
    }

    // ── Render loop ───────────────────────────────────────────────────────
    let angleY = 0;
    let angleX = 0;
    let active = false;

    const PROJ = perspective(Math.PI / 3, 1.0, 0.1, 50.0);
    const VIEW = transl(0, 0, -4.5);

    function frame() {
        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.clearColor(0.031, 0.024, 0.071, 1.0);  // matches card background
        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

        if (active) {
            angleY += 0.007;
            angleX += 0.0023;   // slower X so all 6 faces appear over time

            const model = mul(rotX(angleX), rotY(angleY));
            const mvp   = mul(PROJ, mul(VIEW, model));

            gl.uniformMatrix4fv(uMvp,   false, mvp);
            gl.uniformMatrix4fv(uModel, false, model);
            gl.uniform1i(uTex, 0);

            gl.activeTexture(gl.TEXTURE0);
            gl.bindBuffer(gl.ARRAY_BUFFER, vBuf);
            gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, iBuf);
            bindAttribs();

            for (let face = 0; face < 6; face++) {
                gl.bindTexture(gl.TEXTURE_2D, texForFace(face));
                // 6 indices per face, each index is 2 bytes (UNSIGNED_SHORT)
                gl.drawElements(gl.TRIANGLES, 6, gl.UNSIGNED_SHORT, face * 6 * 2);
            }
        }

        requestAnimationFrame(frame);
    }

    // ── updateDisplay (called by metadata-streaming.js) ───────────────────
    window.updateDisplay = function (metadata) {
        const card = document.getElementById('card');
        if (!metadata || !metadata.title) {
            document.getElementById('track-artist').textContent = '';
            document.getElementById('track-title').textContent  = '';
            document.getElementById('track-album').textContent  = '';
            card.classList.remove('visible');
            active = false;
            return;
        }

        const isNew = document.getElementById('track-artist').textContent !== (metadata.artist || '');
        document.getElementById('track-artist').textContent = metadata.artist || '';
        document.getElementById('track-title').textContent  = metadata.title  || '';
        document.getElementById('track-album').textContent  = metadata.album  || '';
        card.classList.add('visible');
        active = true;

        if (isNew) {
            // Reset cover + fanart for the new track
            coverTex = null;
            faceTex.fill(null);
            if (metadata.coverimagebase64) {
                loadFromB64(metadata.coverimagebase64).then(tex => { if (tex) coverTex = tex; });
            }
            if (metadata.artist) fetchFanart(metadata.artist);
        }
    };

    connectImagesWs();
    requestAnimationFrame(frame);
}());
