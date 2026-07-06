// WebGL Plasma Background
// Classic demoscene plasma: five overlapping sine waves at irrational time
// speeds index into the cover art palette for a continuously flowing field.
'use strict';

const FRAG_SRC = WNPPaletteBg.GLSL + `
    void main() {
        float t = u_time;
        vec2 uv = v_uv - 0.5;
        uv.x *= u_ar;

        // Five overlapping sine waves. Spatial frequencies are distinct
        // primes; time speeds have no simple sums/ratios so the waves
        // never periodically cancel and stall the motion.
        float v = 0.0;
        v += sin(uv.x * 3.0 + t);
        v += sin(uv.y * 5.0 + t * 0.7);
        v += sin((uv.x + uv.y) * 7.0 + t * 1.3);
        v += sin(length(uv) * 9.0 - t * 1.9);
        v += sin((uv.x - uv.y * 0.5) * 4.0 + t * 2.3);

        // Normalize [-5, 5] → [0, 1) and use as palette position.
        float pv = fract(v * 0.1 + 0.5);

        vec3 col = mix(sampleA(pv), sampleB(pv), u_blend);
        gl_FragColor = vec4(col, 1.0);
    }
`;

WNPPaletteBg.init(FRAG_SRC);
