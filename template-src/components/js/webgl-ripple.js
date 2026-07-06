// WebGL Ripple Background
// Two ring sources with chained fluid physics:
//   1. Angular twist  — r0 is scaled by a spinning angle function, turning
//      concentric circles into rotating gear/flower wavefronts.
//   2. Fluid refraction — ring 0's wave energy warps the coordinate space
//      that ring 1 travels through, so ring 1's wavefronts realistically
//      bend and lens around ring 0's centre.
'use strict';

const FRAG_SRC = WNPPaletteBg.GLSL + `
    void main() {
        float t  = u_time;
        vec2  uv = v_uv - 0.5;
        uv.x    *= u_ar;

        // Two slowly drifting ring sources.
        vec2 c0 = vec2(0.0, 0.0);
        vec2 c1 = vec2(0.3 * sin(t * 0.31), 0.22 * cos(t * 0.23));

        // Angular twist: modulate r0 by the viewing angle so circles become
        // spinning gear shapes.  Symmetry is broken at the wave source itself.
        float theta = atan(uv.y, uv.x);
        float r0 = length(uv - c0) * (1.0 + sin(theta * 4.0 + t * 0.2) * 0.15);
        float v  = sin(r0 * 12.0 - t * 2.0);

        // Fluid refraction: use ring 0's wave energy to warp the space ring 1
        // propagates through.  The gear-shaped wavefronts of ring 0 now lens
        // ring 1's rings into an asymmetric heavy-liquid distortion.
        vec2 warpedUV1 = uv - c1 + uv * v * 0.04;
        float r1 = length(warpedUV1);
        v += sin(r1 * 9.0 - t * 1.7);

        float pv = fract(v * 0.25 + 0.5);
        vec3  col = mix(sampleA(pv), sampleB(pv), u_blend);
        gl_FragColor = vec4(col, 1.0);
    }
`;

WNPPaletteBg.init(FRAG_SRC);
