// WebGL Noise Field Background
// Domain-warped fractal Brownian motion: a smooth noise field is used to
// distort the input to a second noise field, producing organic swirling
// cloud-like textures that drift slowly over time.
'use strict';

const FRAG_SRC = WNPPaletteBg.GLSL + `
    float hash(vec2 p) {
        return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
    }

    // Bilinear-interpolated smooth value noise.
    float smoothNoise(vec2 p) {
        vec2 i = floor(p);
        vec2 f = fract(p);
        f = f * f * (3.0 - 2.0 * f); // cubic smoothstep kernel
        return mix(mix(hash(i),                hash(i + vec2(1.0, 0.0)), f.x),
                   mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
    }

    // Four-octave fBm — each octave uses a unique offset to avoid lattice overlap.
    float fbm(vec2 p) {
        float v  = smoothNoise(p)               * 0.5000;
        v += smoothNoise(p * 2.0 + vec2(1.7, 9.2)) * 0.2500;
        v += smoothNoise(p * 4.0 + vec2(8.3, 2.8)) * 0.1250;
        v += smoothNoise(p * 8.0 + vec2(3.1, 6.4)) * 0.0625;
        return v / 0.9375; // normalize to [0, 1]
    }

    void main() {
        float t  = u_time;
        vec2  uv = vec2(v_uv.x * u_ar, v_uv.y) * 2.0;

        // Slowly drift the domain so the field evolves over time.
        vec2 p = uv + vec2(t * 0.05, t * 0.03);

        // Domain warp: use one fbm to distort the input to another.
        // This produces the characteristic swirling, folded-cloud look.
        vec2 q  = vec2(fbm(p), fbm(p + vec2(1.0, 1.0)));
        float pv = fbm(p + q * 0.4 + vec2(t * 0.02, t * 0.01));

        vec3 col = mix(sampleA(pv), sampleB(pv), u_blend);
        gl_FragColor = vec4(col, 1.0);
    }
`;

WNPPaletteBg.init(FRAG_SRC);
