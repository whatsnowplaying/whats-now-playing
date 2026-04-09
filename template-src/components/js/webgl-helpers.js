// Shared WebGL utility functions for WNP overlay templates
'use strict';

const WNPWebGL = (function () {
    /** Compile both shaders, link a program, call useProgram, and return it. */
    function compileProgram(gl, vertSrc, fragSrc) {
        function compile(type, src) {
            const s = gl.createShader(type);
            gl.shaderSource(s, src);
            gl.compileShader(s);
            if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
                console.error('WNPWebGL shader error:', gl.getShaderInfoLog(s));
            }
            return s;
        }
        const prog = gl.createProgram();
        gl.attachShader(prog, compile(gl.VERTEX_SHADER,   vertSrc));
        gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, fragSrc));
        gl.linkProgram(prog);
        if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
            console.error('WNPWebGL link error:', gl.getProgramInfoLog(prog));
        }
        gl.useProgram(prog);
        return prog;
    }

    /**
     * Create and bind a full-screen triangle-strip quad for fragment-shader templates.
     * Binds the `a_pos` attribute from the given program.
     */
    function fullscreenQuad(gl, prog) {
        const buf = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, buf);
        gl.bufferData(gl.ARRAY_BUFFER,
            new Float32Array([-1, -1,  1, -1,  -1, 1,  1, 1]), gl.STATIC_DRAW);
        const aPos = gl.getAttribLocation(prog, 'a_pos');
        gl.enableVertexAttribArray(aPos);
        gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);
        return buf;
    }

    return { compileProgram, fullscreenQuad };
}());
