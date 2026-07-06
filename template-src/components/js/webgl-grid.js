// WebGL Digital Grid Background
// Two nested grids (fine + coarse) drawn with step(threshold, fract())
// for razor-sharp lines.  A slow color field drifts across the canvas so
// each section of the grid picks up a different palette hue.  Intersection
// nodes where coarse lines cross get a brief complementary-hue flash.
'use strict';

const FRAG_SRC = WNPPaletteBg.GLSL + `
    void main() {
        float t  = u_time;
        vec2  uv = vec2(v_uv.x * u_ar, v_uv.y);

        // Slow palette-colour field that drifts across the grid over time.
        float field = sin(uv.x * 1.2 + t * 0.08)
                    + sin(uv.y * 1.8 - t * 0.06)
                    + sin((uv.x + uv.y) * 0.9 + t * 0.05);
        float pv = fract(field * 0.166 + 0.5);

        // Fine grid: 20 cells across canvas height, lines are 4% of cell width.
        float fx = step(0.96, fract(uv.x * 20.0));
        float fy = step(0.96, fract(uv.y * 20.0));

        // Coarse grid: every 5th fine cell (4× larger), lines are 3% of cell.
        float cx = step(0.97, fract(uv.x * 5.0));
        float cy = step(0.97, fract(uv.y * 5.0));

        float fine   = max(fx, fy);
        float coarse = max(cx, cy);
        // Intersection node: where both coarse axes cross simultaneously.
        float node   = cx * cy;

        vec3 lineCol  = mix(sampleA(pv),            sampleB(pv),            u_blend);
        vec3 nodeCol  = mix(sampleA(fract(pv+0.5)), sampleB(fract(pv+0.5)), u_blend);
        vec3 dark     = mix(u_palette_a[0],          u_palette_b[0],          u_blend) * 0.04;

        vec3 col = dark;
        col = mix(col, lineCol * 0.45, fine);    // fine grid, dimmer
        col = mix(col, lineCol,        coarse);   // coarse grid, full brightness
        col = min(col + nodeCol * node, vec3(1.0)); // intersection flash

        gl_FragColor = vec4(col, 1.0);
    }
`;

WNPPaletteBg.init(FRAG_SRC);
