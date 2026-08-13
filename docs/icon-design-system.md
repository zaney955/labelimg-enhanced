# LabelImg Enhanced operation icon system

## Scope

The operation icon set contains the 76 SVG files used by actions and buttons. The
application identity asset, `app.svg`, is outside this system.

The icons are designed from action names and behavior. Existing icon artwork is
not a visual reference.

## V2 construction grammar

- Canvas: 24 × 24 with a transparent background.
- Smallest target: the source geometry is designed at 16 × 16 first, then
  inspected at 20 × 20, 24 × 24, and presentation sizes. It is not a detailed
  large icon scaled down.
- Optical footprint: the primary silhouette occupies 14–16 source units and is
  centered on `(12, 12)`. Secondary action marks may extend to a maximum
  18 × 18 envelope. Filled and circular silhouettes are reduced optically so
  they do not appear larger than open shapes.
- Stroke: every visible line is 1.8 source units. All lines use round caps and
  round joins. Dashed strokes, isolated heavy bars, mixed stroke widths, and
  hairlines are forbidden.
- Corners: object corners use a 2-unit radius; compact internal corners use a
  1-unit radius. Sharp corners are reserved only for semantic arrowheads,
  checkmarks, pointer tips, and document folds.
- Construction: one softly tinted primary object, one functional-color contour,
  and at most one simplified secondary mark. No icon may mix outline, solid,
  dashed, and broken-corner grammars.
- Detail budget: one primary object and one supporting mark, with at least
  1.8 source units of negative space between unrelated strokes.
- Effects: no gradients, shadows, highlights, texture, or enclosing tile.
- Typography: no SVG `text` elements or font dependency. Language glyphs are
  paths; annotation-format icons use structural marks instead of abbreviations.
- Accessibility: related icons share a motif, but every icon remains identifiable
  by silhouette and structure without color.

## Duotone responsibilities

- **Functional color** draws the complete outer contour and every action/state
  mark: arrows, plus signs, checks, handles, and magnifiers. It answers “what
  family or operation is this?”
- **Structure color** is allowed only for one passive internal feature of the
  object: stored content, an image horizon, a document hierarchy, or an edit
  instrument. It never replaces half of the outer contour and never functions
  as arbitrary emphasis.
- **Tint** is a low-contrast fill clipped inside the primary object. It supplies
  visual mass but never carries meaning by itself.
- A symbol that remains clear without a passive internal feature omits the
  structure color instead of adding decoration.

## Semantic motifs

- Creation: a complete bounding box plus a functional-color plus sign. No
  marching ants or dotted selection border.
- Selection and editing: a complete bounding box with control handles plus one
  diagonal edit instrument. A pointer alone means selection and is insufficient.
- Verification: an annotation document plus a check. Shields are reserved for
  security and must not represent review state.
- VOC: a document plus an XML hierarchy mark. Generic nested squares alone are
  insufficient to identify the storage format.
- Language choice: one speech surface plus a large, simplified path glyph. The
  glyph must retain open counters at 16 px.

## Light-theme palette

| Role | Stroke | Tint | Use |
| --- | --- | --- | --- |
| Structure | `#455468` | — | One passive internal feature only |
| File and navigation | `#5677A6` | `#DCE6F2` | Files, folders, save, movement |
| Annotation editing | `#756B9E` | `#E6E2F0` | Boxes, labels, selection |
| Image processing | `#4F8582` | `#DCEBE8` | Crop, transform, adjustment |
| View controls | `#64788F` | `#E2E8EE` | Zoom, visibility, fitting |
| Success | `#5F8468` | `#DFEADF` | Completion and verification |
| Warning | `#9A7640` | `#F0E6D4` | Inspection and attention |
| Destructive | `#A65F5F` | `#F1DEDE` | Delete, close, quit |
| Language and preferences | `#7B6F94` | `#E8E2EE` | Language and settings |

Colors are restrained accents for a light application theme. Destructive,
warning, and success roles may override a feature family's usual color, but
shape always carries the same meaning.

## Implementation

All 76 operation SVGs implement this grammar. `app.svg` remains the separate
application identity asset. The complete review sheet is
[`icon-review-all.png`](./icon-review-all.png).

Automated verification covers:

- exactly 76 operation SVGs and one application SVG;
- the shared 24 × 24 canvas, 1.8-unit stroke, round caps, and round joins;
- the approved functional colors, structure color, and family tints;
- absence of fonts, embedded images, scripts, styles, and dashed strokes;
- nonempty, inset rendering at 16, 20, and 24 pixels;
- unique 24-pixel raster output for every operation icon; and
- byte-identical Qt rendering between each source SVG and its compiled resource.
