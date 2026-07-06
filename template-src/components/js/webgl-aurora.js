// WebGL Aurora Background
// Three curtains of light drift across the screen, each tinted toward a
// different section of the cover art palette.  The curtains undulate with
// layered sine waves to mimic real auroral shimmering.
'use strict';

const FRAG_SRC = WNPPaletteBg.GLSL + `
    // One aurora curtain: Gaussian falloff from a sine-warped centre line.
    float curtain(float y, float cy, float x, float t,
                  float freq, float speed, float sharp) {
        float dy = y - cy
                 - sin(x * freq        + t * speed)        * 0.07
                 - sin(x * freq * 1.7  + t * speed * 0.6)  * 0.035;
        return exp(-dy * dy * sharp);
    }

    void main() {
        float t  = u_time;
        float x  = v_uv.x * u_ar;
        float y  = v_uv.y;

        // Three bands at different heights with distinct frequencies and speeds.
        float b0 = curtain(y, 0.65, x, t, 2.1, 0.28, 90.0);
        float b1 = curtain(y, 0.50, x, t, 3.3, 0.19, 130.0);
        float b2 = curtain(y, 0.35, x, t, 1.7, 0.35, 70.0);
        float total = b0 + b1 + b2;

        // Each curtain draws from a different third of the palette.
        vec3 colA = (sampleA(0.0)  * b0 +
                     sampleA(0.33) * b1 +
                     sampleA(0.66) * b2) / max(total, 0.001);
        vec3 colB = (sampleB(0.0)  * b0 +
                     sampleB(0.33) * b1 +
                     sampleB(0.66) * b2) / max(total, 0.001);
        vec3 col = mix(colA, colB, u_blend);

        // Very dark sky behind the curtains.
        vec3 sky = mix(u_palette_a[0], u_palette_b[0], u_blend) * 0.04;
        float brightness = clamp(total * 1.5, 0.0, 1.0);
        col = mix(sky, col, brightness);

        gl_FragColor = vec4(col, 1.0);
    }
`;

WNPPaletteBg.init(FRAG_SRC);
