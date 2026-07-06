// WebGL Gradient Sweep Background
// A smooth palette gradient whose direction slowly rotates, with gentle
// sine-product distortion to prevent hard banding.
'use strict';

const FRAG_SRC = WNPPaletteBg.GLSL + `
    void main() {
        float t  = u_time;
        vec2 uv  = v_uv - 0.5;
        uv.x    *= u_ar;

        // Direction vector rotates once every ~90 seconds.
        float angle = t * 0.07;
        vec2  dir   = vec2(cos(angle), sin(angle));
        float proj  = dot(uv, dir);

        // Gentle sine-product distortion to break up pure linearity.
        proj += sin(uv.x * 3.0 + t * 0.4) * sin(uv.y * 2.5 + t * 0.3) * 0.06;

        float pv = fract(proj * 0.5 + 0.5);
        vec3  col = mix(sampleA(pv), sampleB(pv), u_blend);
        gl_FragColor = vec4(col, 1.0);
    }
`;

WNPPaletteBg.init(FRAG_SRC);
