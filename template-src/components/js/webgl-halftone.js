// WebGL Halftone Dot Matrix Background
// The canvas is divided into a uniform grid of cells.  Inside each cell
// a sharp circle is drawn; its radius is driven by an underlying slow
// plasma wave sampled at the cell centre (not per-pixel, so the dots are
// uniformly sized within each cell — no noise).  Dense cells glow large
// and full-colour; sparse cells shrink toward a faint complementary tint.
'use strict';

const FRAG_SRC = WNPPaletteBg.GLSL + `
    void main() {
        float t   = u_time;
        vec2  uv  = vec2(v_uv.x * u_ar, v_uv.y);

        // Divide into 28 cells across canvas height.
        float cells  = 28.0;
        vec2  cellId = floor(uv * cells);
        vec2  local  = fract(uv * cells) - 0.5; // [-0.5, 0.5] within cell

        // Sample the slow plasma at the cell centre, not at the pixel.
        // This ensures the dot radius is constant within each cell.
        vec2  cc = (cellId + 0.5) / cells;
        float wave = sin(cc.x * u_ar * 3.1 + t * 0.60)
                   + sin(cc.y * 4.7        - t * 0.40)
                   + sin((cc.x + cc.y) * u_ar * 3.7 + t * 0.30);
        float density = clamp(wave * 0.20 + 0.55, 0.06, 0.94);

        // Sharp-edged circle; radius proportional to density.
        float r   = density * 0.46;
        float dot = 1.0 - step(r, length(local));

        // Dot hue shifts slowly across the grid so adjacent cells differ.
        float pv    = fract(density + sin(cc.x * 2.3 + t * 0.05) * 0.2);
        vec3 dotCol = mix(sampleA(pv),            sampleB(pv),            u_blend);
        // Background: faint complementary tint instead of pure black.
        vec3 bgCol  = mix(sampleA(fract(pv+0.5)), sampleB(fract(pv+0.5)), u_blend) * 0.07;

        vec3 col = mix(bgCol, dotCol, dot);
        gl_FragColor = vec4(col, 1.0);
    }
`;

WNPPaletteBg.init(FRAG_SRC);
