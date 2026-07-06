// WebGL Magma Rise Background
// Aurora turned on its side: vertical heat columns rise from the bottom,
// with a steady upward drift in the noise so the texture constantly tears
// upward like fire or magma venting through the floor.
'use strict';

const FRAG_SRC = WNPPaletteBg.GLSL + `
    // One heat column: Gaussian falloff from a sine-warped vertical centre line.
    float column(float x, float cx, float y, float t,
                 float freq, float speed, float sharp) {
        float dx = x - cx
                 - sin(y * freq        + t * speed)        * 0.07
                 - sin(y * freq * 1.7  + t * speed * 0.6)  * 0.035;
        return exp(-dx * dx * sharp);
    }

    void main() {
        float t   = u_time;
        float x   = v_uv.x * u_ar;
        // Add upward bias so the noise scrolls toward the top of the screen.
        float y   = v_uv.y - t * 0.18;

        // Four columns spread across the width.
        float c0 = column(x, u_ar*0.18, y, t, 2.1, 0.31, 85.0);
        float c1 = column(x, u_ar*0.40, y, t, 3.4, 0.20, 120.0);
        float c2 = column(x, u_ar*0.62, y, t, 1.8, 0.37, 95.0);
        float c3 = column(x, u_ar*0.83, y, t, 2.9, 0.24, 110.0);
        float raw = c0 + c1 + c2 + c3;

        // Heat fades toward the top (v_uv.y = 1 = top in screen space).
        float heat = (1.0 - v_uv.y) * (1.0 - v_uv.y);

        // Weighted palette color from each column's position.
        float r = max(raw, 0.001);
        vec3 colA = (sampleA(0.0)  * c0 + sampleA(0.33) * c1 +
                     sampleA(0.66) * c2 + sampleA(1.0)  * c3) / r;
        vec3 colB = (sampleB(0.0)  * c0 + sampleB(0.33) * c1 +
                     sampleB(0.66) * c2 + sampleB(1.0)  * c3) / r;
        vec3 col  = mix(colA, colB, u_blend);

        // Dark background; brightness scaled by heat gradient.
        vec3 dark = mix(u_palette_a[0], u_palette_b[0], u_blend) * 0.04;
        float brightness = clamp(raw * heat * 2.5, 0.0, 1.0);
        col = mix(dark, col, brightness);

        gl_FragColor = vec4(col, 1.0);
    }
`;

WNPPaletteBg.init(FRAG_SRC);
