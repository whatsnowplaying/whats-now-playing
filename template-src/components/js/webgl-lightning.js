// WebGL Electric / Neon Lightning Background
// Aurora-style curtains collapsed to razor-thin tendrils by a sharp
// smoothstep.  The tender core is white-hot; a soft outer glow carries
// the palette colour.  Dark background so the strands read as neon.
'use strict';

const FRAG_SRC = WNPPaletteBg.GLSL + `
    float strand(float y, float cy, float x, float t,
                 float freq, float speed, float sharp) {
        float dy = y - cy
                 - sin(x * freq        + t * speed)        * 0.06
                 - sin(x * freq * 1.9  + t * speed * 0.7)  * 0.03
                 - sin(x * freq * 0.5  + t * speed * 1.4)  * 0.02;
        return exp(-dy * dy * sharp);
    }

    void main() {
        float t  = u_time;
        float x  = v_uv.x * u_ar;
        float y  = v_uv.y;

        // Three strands at different heights with distinct warp parameters.
        float s0 = strand(y, 0.65, x, t, 2.3, 0.41, 180.0);
        float s1 = strand(y, 0.50, x, t, 3.7, 0.27, 240.0);
        float s2 = strand(y, 0.35, x, t, 1.6, 0.55,  90.0);
        float total = s0 + s1 + s2;

        // Weighted palette colour from each strand's vertical position.
        float r = max(s0 + s1 + s2, 0.001);
        vec3 colA = (sampleA(0.0) * s0 + sampleA(0.5) * s1 + sampleA(1.0) * s2) / r;
        vec3 colB = (sampleB(0.0) * s0 + sampleB(0.5) * s1 + sampleB(1.0) * s2) / r;
        vec3 paletteCol = mix(colA, colB, u_blend);

        // Two zones: soft outer glow and razor-thin bright core.
        float glow  = smoothstep(0.0, 0.7, total);
        float core  = smoothstep(0.85, 0.97, total);

        // Dark base; glow adds colour; core bleaches toward white.
        vec3 dark = vec3(0.0, 0.0, 0.03);
        vec3 col  = mix(dark, paletteCol, glow);
        col = mix(col, vec3(1.0), core * 0.92);

        gl_FragColor = vec4(col, 1.0);
    }
`;

WNPPaletteBg.init(FRAG_SRC);
