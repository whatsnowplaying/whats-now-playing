// WebGL Cosmic Nebula Background
// Large-scale color regions (from slow domain drift) overlay small-scale
// gas-cloud density (from higher-frequency FBM), then density brightens the
// scene — dense peaks glow, sparse voids go dark.  Distinct from noise-field's
// domain-warp approach: this one uses two separate noise lookups (structure vs
// density) and mixes them additively rather than recursively.
'use strict';

const FRAG_SRC = WNPPaletteBg.GLSL + `
    float hash(vec2 p) {
        return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
    }

    float smoothNoise(vec2 p) {
        vec2 i = floor(p);
        vec2 f = fract(p);
        f = f * f * (3.0 - 2.0 * f);
        return mix(mix(hash(i),                hash(i + vec2(1.0, 0.0)), f.x),
                   mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
    }

    // Low-frequency FBM: sets the large-scale colour region.
    float fbmLow(vec2 p) {
        float v  = smoothNoise(p)                      * 0.5000;
        v += smoothNoise(p * 2.0 + vec2(3.4, 7.1))    * 0.2500;
        v += smoothNoise(p * 4.0 + vec2(1.2, 5.6))    * 0.1250;
        return v / 0.875;
    }

    // High-frequency FBM: sets gas-cloud density within each region.
    float fbmHigh(vec2 p) {
        float v  = smoothNoise(p)                      * 0.5000;
        v += smoothNoise(p * 2.0 + vec2(9.2, 1.7))    * 0.2500;
        v += smoothNoise(p * 4.0 + vec2(4.4, 8.3))    * 0.1250;
        v += smoothNoise(p * 8.0 + vec2(2.1, 3.8))    * 0.0625;
        v += smoothNoise(p * 16.0 + vec2(6.7, 0.9))   * 0.0313;
        return v / 0.9688;
    }

    void main() {
        float t   = u_time;
        vec2  uv  = vec2(v_uv.x * u_ar, v_uv.y);

        // Large-scale colour structure drifts very slowly.
        vec2 pLow  = uv * 0.4  + vec2(t * 0.007, t * 0.005);
        // Gas-cloud density drifts faster at a finer scale.
        vec2 pHigh = uv * 1.8  + vec2(t * 0.025, t * 0.018);

        float structure = fbmLow(pLow);    // large-scale hue [0,1]
        float density   = fbmHigh(pHigh);  // local gas density [0,1]

        // Small secondary swirl adds a hint of nebula arms.
        float swirl = fbmLow(uv * 0.25 + vec2(t * 0.003, -t * 0.004));
        float pv = fract(structure * 0.7 + swirl * 0.3);

        vec3 col = mix(sampleA(pv), sampleB(pv), u_blend);

        // Dense regions glow brightly; sparse voids nearly black.
        float brightness = 0.05 + density * density * 1.8;
        col *= brightness;

        gl_FragColor = vec4(col, 1.0);
    }
`;

WNPPaletteBg.init(FRAG_SRC);
