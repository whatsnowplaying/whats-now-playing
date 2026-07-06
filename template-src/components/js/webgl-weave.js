// WebGL Geometric Weave Background
// Two sine grids at different angles are overlaid and their interference
// value drives the palette lookup — like a Moiré pattern or textile weave.
// A slow rotation of both grids keeps the pattern alive over time.
'use strict';

const FRAG_SRC = WNPPaletteBg.GLSL + `
    void main() {
        float t   = u_time;
        vec2  uv  = vec2(v_uv.x * u_ar, v_uv.y);

        // Slowly counter-rotate the two grid directions.
        float rot0 =  t * 0.04;
        float rot1 = -t * 0.03;

        // Grid 0: rotated sine stripes.
        vec2 d0  = vec2(cos(rot0), sin(rot0));
        float g0 = sin(dot(uv, d0) * 18.0);

        // Grid 1: different angle + frequency, opposite rotation.
        vec2 d1  = vec2(cos(rot1 + 1.047), sin(rot1 + 1.047)); // +60°
        float g1 = sin(dot(uv, d1) * 14.0);

        // Grid 2: third axis to enrich the weave.
        vec2 d2  = vec2(cos(rot0 + 2.094), sin(rot0 + 2.094)); // +120°
        float g2 = sin(dot(uv, d2) * 11.0);

        // Interference value — average of the three grids.
        float v = (g0 + g1 + g2) / 3.0; // [-1, 1]

        // Map to palette.
        float pv = v * 0.5 + 0.5;
        vec3  col = mix(sampleA(pv), sampleB(pv), u_blend);
        gl_FragColor = vec4(col, 1.0);
    }
`;

WNPPaletteBg.init(FRAG_SRC);
