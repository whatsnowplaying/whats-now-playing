// WebGL Flow Field Background
// A vector field of angles is computed from a hash at each grid cell.
// Streamlines follow those angles, producing long directed strokes that
// bend in unison — like wind over terrain or current in a river.
// Color is driven by the angle itself so adjacent flow regions show
// different palette hues.
'use strict';

const FRAG_SRC = WNPPaletteBg.GLSL + `
    float hash(vec2 p) {
        return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
    }

    // Smooth noise for the angle field.
    float smoothNoise(vec2 p) {
        vec2 i = floor(p);
        vec2 f = fract(p);
        f = f * f * (3.0 - 2.0 * f);
        return mix(mix(hash(i),                hash(i + vec2(1.0, 0.0)), f.x),
                   mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
    }

    void main() {
        float t  = u_time;
        vec2  uv = vec2(v_uv.x * u_ar, v_uv.y);

        // Two-octave noise field to set the flow angle at each point.
        // The slow time drift makes the field rotate and shift over time.
        vec2  fp  = uv * 2.5 + vec2(t * 0.04, t * 0.03);
        float n0  = smoothNoise(fp);
        float n1  = smoothNoise(fp * 2.0 + vec2(5.2, 1.3));
        float angle = (n0 * 0.7 + n1 * 0.3) * 6.2832; // [0, 2π]

        // Project the pixel onto the local flow direction.
        vec2 dir    = vec2(cos(angle), sin(angle));
        float along = dot(uv, dir);          // position along the streamline
        float across = dot(uv, vec2(-dir.y, dir.x)); // position across it

        // Stripes along the flow direction — thin bright lines.
        float stripe = step(0.88, fract(across * 14.0 + t * 0.1));

        // Slow-moving brightness pulse along each streamline.
        float pulse = sin(along * 8.0 - t * 1.5) * 0.5 + 0.5;

        // Palette: hue from the flow angle, brightness from stripe/pulse.
        float pv    = fract(angle / 6.2832);
        vec3 flowCol = mix(sampleA(pv), sampleB(pv), u_blend);
        vec3 dark    = mix(u_palette_a[0], u_palette_b[0], u_blend) * 0.06;

        float brightness = clamp(stripe * pulse * 1.8, 0.0, 1.0);
        vec3  col = mix(dark, flowCol, brightness);
        gl_FragColor = vec4(col, 1.0);
    }
`;

WNPPaletteBg.init(FRAG_SRC);
