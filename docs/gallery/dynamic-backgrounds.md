# Dynamic Background Gallery

Dynamic backgrounds are full-screen WebGL effects that fill the entire OBS browser source
canvas and automatically adapt their color palette to the current track's cover art.
Every background cross-fades to a new palette when the track changes.

All backgrounds are designed for use as a **Background** layer in OBS, placed behind your
track info overlay. Set the OBS browser source to your stream resolution (typically 1920 × 1080).

Because these effects use the cover art palette rather than a fixed color scheme, they
automatically look cohesive with whatever is playing — a warm orange palette for funk,
cool blues for ambient, saturated neons for EDM.

## How the Palette Works

Each background reads two palette fields from the WebSocket stream:

* `cover_palette_lighting` — vibrant colors extracted from the cover art, filtered for
  saturation and brightness. Used when 3 or more distinct colors are available.
* `cover_palette` — a broader extraction with minimal filtering. Used as a fallback for
  monochromatic or near-black covers (white sleeves, single-color artwork).

The background smoothly cross-fades between the outgoing and incoming palettes over
approximately 1.5 seconds on each track change.

## Organic Effects

### ws-webgl-plasma-background

Overlapping sine waves at five irrational frequencies produce a continuously shifting
color field with no repeating pattern. Colors from the cover palette flow and blend
across the full canvas.

### ws-webgl-aurora-background

Three drifting curtains of light rendered as Gaussian falloff from sine-warped centre
lines, layered over a near-black background. Each curtain draws from a different
third of the cover palette, producing the characteristic layered glow of aurora borealis.

### ws-webgl-gradient-sweep-background

A smooth palette gradient slowly rotates across the screen using a direction-projected
sine wave with subtle distortion. Lower energy than plasma — good for backgrounds
behind dense text layouts.

### ws-webgl-voronoi-background

Six seed points orbit slowly across the canvas, each cell colored by the cover palette
entry nearest its index. Cell borders are softened with a smoothstep ramp. Produces
a stained-glass or crystalline look that shifts as the seeds drift.

### ws-webgl-noise-field-background

Domain-warped fractal Brownian motion: one noise field distorts the input coordinates
of a second noise field, producing organic swirling clouds that slowly evolve. Similar
to the nebula effect but with more aggressive domain warping for tighter, faster swirls.

### ws-webgl-ripple-background

Two ring sources with chained fluid physics: the wavefronts of the first ring are
twisted into a gear/flower shape by an angular modulator, then the energy of those
waves warps the coordinate space of the second ring, so the second set of rings
visibly bends and lenses around the first center point.

### ws-webgl-magma-rise-background

Four vertical heat columns drift upward across the canvas, with the heat intensity
fading toward the top. The column positions undulate sinusoidally, and the upward
drift in the noise field makes the texture tear upward like fire or magma venting
from below. Good match for high-energy or heavy music.

### ws-webgl-nebula-background

Two separate fractal noise lookups at different frequencies — a low-frequency field
sets large-scale color regions, a high-frequency field sets gas-cloud density within
each region. Dense areas glow brightly; sparse voids go nearly black. Produces the
dramatic void/cloud contrast of nebula photography.

### ws-webgl-lightning-background

Aurora-style curtains collapsed to razor-thin tendrils by a tight smoothstep.
A second, wider smoothstep adds a soft colored glow around each strand; the
sharpest peaks bleach toward white, producing a neon tube effect on a near-black
background. Good for electronic, industrial, or cyberpunk aesthetics.

## Geometric / Structured Effects

### ws-webgl-grid-background

Two nested grids drawn with `step(threshold, fract(coordinate))` for razor-sharp
lines with no antialiasing. A slow color field drifts across the canvas so adjacent
sections of the grid carry different palette hues. Coarse grid intersection nodes
flash a complementary-hue highlight. Looks like a HUD, blueprint, or architectural
scaffolding — consistent across any screen split.

### ws-webgl-halftone-background

The canvas is divided into a uniform grid of cells. Inside each cell, a hard-edged
circle is drawn; its radius is driven by an underlying plasma wave sampled at the
cell centre (not per-pixel, so dots are uniformly round within each cell). Dense
regions produce large dots; sparse regions shrink toward a faint background tint.
Looks like an LED stadium screen or printed comic-book halftone.

### ws-webgl-flow-field-background

A vector field of angles is derived from smooth noise, then evaluated as directional
streamlines: bright stripe pulses travel along the flow direction while the
perpendicular axis controls stripe width. The palette hue is taken directly from
the local flow angle, so different flow regions show different colors. Produces
long directed strokes that bend organically — like wind over terrain.

### ws-webgl-weave-background

Three sine grids spaced 60° apart (to prevent any two ever becoming parallel)
counter-rotate against each other over time. Their interference value drives the
palette lookup, producing a continuously shifting Moiré pattern that resembles
a textile weave, woven screen, or geometric op-art.
