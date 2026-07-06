// WebGL Voronoi Background
// Six seed points drift slowly across the canvas.  Each pixel is colored
// by the palette entry of its nearest seed.  Cell borders are softened
// with a smoothstep on the gap between the two nearest distances.
'use strict';

const FRAG_SRC = WNPPaletteBg.GLSL + `
    void main() {
        float t  = u_time;
        vec2  uv = vec2(v_uv.x * u_ar, v_uv.y);

        // Six seed points with distinct orbit speeds and phases.
        vec2 seeds[6];
        seeds[0] = vec2(u_ar*(0.5+0.38*sin(t*0.23)),      0.5+0.38*cos(t*0.17));
        seeds[1] = vec2(u_ar*(0.5+0.38*cos(t*0.19+2.09)), 0.5+0.38*sin(t*0.13+0.7));
        seeds[2] = vec2(u_ar*(0.5+0.38*sin(t*0.31+4.19)), 0.5+0.38*cos(t*0.27));
        seeds[3] = vec2(u_ar*(0.5+0.38*cos(t*0.17+1.40)), 0.5+0.38*sin(t*0.21+2.1));
        seeds[4] = vec2(u_ar*(0.5+0.38*sin(t*0.13+3.50)), 0.5+0.38*cos(t*0.29+1.0));
        seeds[5] = vec2(u_ar*(0.5+0.38*cos(t*0.29+5.76)), 0.5+0.38*sin(t*0.11+4.2));

        float dists[6];
        for (int i = 0; i < 6; i++) {
            dists[i] = distance(uv, seeds[i]);
        }

        // Find nearest (m1) and second-nearest (m2) distances in one pass.
        float m1 = 1000.0, m2 = 1000.0;
        int   mi = 0;
        for (int i = 0; i < 6; i++) {
            if (dists[i] < m1) { m2 = m1; m1 = dists[i]; mi = i; }
            else if (dists[i] < m2) { m2 = dists[i]; }
        }

        // Map nearest seed index to palette position [0, 1).
        float pv = float(mi) / 5.0;
        vec3 col = mix(sampleA(pv), sampleB(pv), u_blend);

        // Darken at cell boundaries.
        float border = smoothstep(0.0, 0.04, m2 - m1);
        col *= border;

        gl_FragColor = vec4(col, 1.0);
    }
`;

WNPPaletteBg.init(FRAG_SRC);
