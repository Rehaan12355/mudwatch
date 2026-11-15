# Design System: Mudslide Watch

The single source of truth for how Mudslide Watch looks and behaves. The product is
one map for three audiences: a resident checking their street, a county planner, and a
hackathon judge with thirty seconds. Every number on screen comes from the pipeline.
Nothing in the interface is decorative data.

## 1. Visual Theme & Atmosphere

A survey table at night. The hills are drawn in grey relief, the interface is neutral
zinc, and there is exactly one colour on the whole screen: Cinder red. It appears only
where burned ground, steep ground and people line up. When the map turns red, that is
the entire message, so nothing else is allowed to be red, orange, blue or green.

The idea of the product is three stacked layers, so the interface shows three stacked
plates. That stack is the signature element and the main control.

- **Density 5, daily-app balanced.** One idea per block. No dashboard tiles.
- **Variance 6, offset asymmetric.** Full-bleed map on the left, one reading column on
  the right, a full-width pass strip at the foot. Nothing is centred.
- **Motion 5, fluid and answering.** Motion follows the user's hand (press, toggle,
  drag) and offers exactly one invitation: the play button.

## 2. Color Palette & Roles

One neutral family (zinc), one accent. No second accent anywhere.

- **Soot** (#0E0E10) — the pass strip at the foot of the screen; the darkest tone
- **Char Sheet** (#151517) — header, reading column, dialog
- **Recess** (#1D1D20) — tracks, hover fills, note blocks, page background
- **Raised** (#29292D) — selected tab, map furniture
- **Seam** (#2C2C31) — 1px dividers and control borders
- **Bone** (#F4F4F5) — primary text, the one solid button, focus rings
- **Ash** (#A1A1AA) — secondary text, units, captions
- **Cinder** (#E5482D, saturation 78%) — the single accent. Red zones, mud paths
  (at 45%), homes in a path, the figures that count them. Never used for buttons,
  links, focus or decoration.

Data is drawn in the same neutrals so that Cinder stays alone:

- **Burn scar** — Ash wash (#D4D4D8 at 40%)
- **Steep slope** — a fine Bone diagonal hatch, no fill
- **Homes** — small Ash dots. A home in a mud path is the loudest thing on the map:
  a 30px Cinder disc with a white house glyph and white rim. A home beside a path is
  a Bone ring
- **USGS hazard (compare view)** — Bone at three strengths (8%, 24%, 46%) for Low,
  Moderate, High, so the experts read as white and our screen reads as red
- **Radar and NISAR pictures** — greyscale, as the instruments deliver them
- **Map base** — a dark street map tinted to zinc land (#19191B) and Soot water, with
  pipeline hillshade laid over it, roads as faint light lines, quiet grey labels

Banned: purple, blue, neon, glows, gradients as decoration, pure black (#000000),
warm greys mixed with cool greys. Printing a card switches to dark ink on white paper.

## 3. Typography Rules

- **Display and body:** Geist. Headlines at weight 700 with tracking -0.03em and
  balanced line breaks. Hierarchy comes from weight and colour before size; the
  largest type on screen is the pass date.
- **Body:** Geist 400, 15px with 1.55 leading, lines capped at 62 characters.
- **Mono:** Geist Mono for the things that came off an instrument: pass dates,
  satellite and track names, areas, counts. Tabular numerals everywhere a number
  can change, so digits do not jitter while the slider moves.
- **Banned:** Inter, every serif face, all-caps labels, tracked-out eyebrow labels,
  `LABEL // YEAR` formatting, gradient text.

## 4. Component Stylings

- **Reading order of the column:** the answer first, in plain words ("17 homes could
  be in the path of a mudslide"), then the address check, then where those homes are,
  and only then the layer stack as the explanation of how the map works. Labels use
  everyday words: "Burned area", "Steep ground", "Homes", "satellite pass".
- **Home marker:** a real button on the map. Selecting it opens that home's block
  card; hover and selection invert it to white.
- **Layer stack (signature):** three plates drawn in isometric projection, stacked
  with air between them: Burn scar, Slope, People. Each plate is a toggle button with
  its name and the question it answers beside it. An off plate is an outline; an on
  plate fills with the same texture it has on the map (ash wash, hatch, dots). With
  all three on, a Cinder column joins the plates and one sentence states what red
  means. Hovering a plate lifts it 3px; pressing sets it down.
- **Buttons:** 44px minimum height, 8px radius, hairline Seam border on Char Sheet.
  One solid Bone button per screen ("Play the story"). Header actions are plain text
  links. Pressing moves a button down 1px. No glows, no custom cursors.
- **View switch:** a Recess track with a Raised thumb.
- **Address search:** label above the field, error text below it, Bone focus ring.
  No floating labels.
- **Block list:** rows separated by Seams, never cards. The whole row is the button.
  The count of homes sits right, in Cinder.
- **Block card:** a status line, a definition list of facts in Mono figures, then the
  plain-language note and a numbered "what to do" list on Recess. The wording says
  "could", never "will".
- **Map furniture:** legend, zoom control and story caption float on the
  map with 12px radius and one soft shadow tinted to Soot. Elevation is used only
  here, because these sit above the map. They keep to the corners and never overlap.
- **Pass strip:** an 8px track on Soot that fills with Bone up to a 22px Bone thumb,
  with one tick per month. Left of it the pass date in large Mono; right of it the
  one figure that matters for the layers that are on.
- **Loading:** skeleton blocks shaped like the stack, headline and list they replace.
  No spinners.
- **Empty and error states:** an inline notice saying what is missing and what to do
  (for example a block with no mapped homes says so and points at the map).

## 5. Layout Principles

- CSS Grid throughout: header / stage / pass strip, and map / reading column (420px).
- The map is never covered by content except its own small furniture.
- Contained reading widths: the column is fixed, the methods page caps at 1100px
  with an asymmetric two-column grid (text 7, figures 5).
- The methods page headline carries small inline pictures at type height (the smoky
  optical view and the radar view) as visual punctuation. No text sits on an image.
- Below 860px everything is one column: map first (62dvh), then the column, with the
  pass strip pinned to the bottom. Heights use `dvh`, never `vh`.
- No horizontal scroll at any width. Every tap target is at least 44px.

## 6. Motion & Interaction

- One easing everywhere, a soft spring: `cubic-bezier(0.22, 1, 0.36, 1)`. No linear
  transitions on interface elements.
- Plates lift and settle; list rows cascade in at 30ms per row when the view changes.
- Two perpetual micro-interactions: the play button breathes a faint Bone ring until
  the user first plays or drags, and each home marker sends out a slow Cinder ring
  for as long as it is on the map, because that is where the eye should land.
- The story is choreographed to thirty seconds: smoke, radar, scar, slope, homes,
  experts. Any click stops it.
- Only `transform` and `opacity` are animated. `prefers-reduced-motion` removes the
  cascade, the breathing ring and every transition.

## 7. Anti-Patterns (Banned)

- No emojis or text glyphs standing in for icons; icons are inline SVG.
- No Inter, no serif faces, no all-caps or tracked-out labels.
- No pure black; the darkest tone is Soot (#0E0E10).
- No second accent colour, no neon, no outer glows, no purple, no decorative gradients.
- No rows of equal cards, no card around every block, no centred hero.
- No invented numbers, rounded-for-effect statistics or filler metric tiles. If the
  pipeline did not produce it, it is not on screen.
- No certainty the data cannot support: "could", "risk zone", "screen"; never
  "will", "prediction", "forecast".
- No marketing verbs ("elevate", "seamless", "unleash", "next-gen").
- No "scroll to explore" prompts, bouncing arrows or custom cursors.
- No overlapping text or images; every element has its own space.
- No stock or placeholder imagery. Every picture is satellite data of this fire.
