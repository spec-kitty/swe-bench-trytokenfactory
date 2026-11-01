Spec Kitty helps people and coding agents agree on what to build before they build it. It is the flagship of one kitty brand with several kitty products — Spec Kitty, Brain Kitty, Build Kitty, Kitty Factory and Team Kitty — that share one kitty and one system; the colour of the kitty's bow tie says which product you are in. The brand is a well-read cat in round spectacles: curious, precise, on your side. Everything here should feel like a clear Mediterranean morning at a thoughtful colleague's desk — cloud-white paper, deep-sea ink, one coloured bow tie — never like a toy, and never like a cold dashboard.

## Principles

1. **Precise, not stiff.** Specs are exact; the voice around them is relaxed. Pair a mono spec key with a plain-English sentence.
2. **Light by material, not by decoration.** The feel comes from cloud-white `surface`, `ink` that is deep-sea navy rather than black, the colours of the coast and an editorial serif — not from gradients, emoji or rounded-everything.
3. **The colour lives on the bow tie.** Each product's colour is its identity — the kitty's bow, a product dot, the cover — and nothing else. Controls are ink on paper.
4. **The kitty is a colleague, not a logo sticker.** It shows up when a person needs reassurance or a nudge (empty states, reviews, errors), with a mood that fits the moment.

## Voice

- Speak as "we" for Spec Kitty and "you" for the reader. The kitty, when it speaks, uses "I" and short sentences.
- Sentence case everywhere: "Accept the spec", not "Accept The Spec".
- Plain verbs first: *Write, Decide, Review, Ship.* No "leverage", "unlock", "supercharge", no exclamation marks, no emoji.
- Be specific: "3 work packages need review", not "You have items pending".
- When something breaks, say what happened, then what to do: "The plan references WP04, which doesn't exist yet. Add it or remove the reference."

| Say | Don't say |
| --- | --- |
| Let's check the acceptance criteria first. | 🚀 Ready to supercharge your workflow? |
| Two decisions are still open. | Oops! Something went wrong. |
| Signed off by Nadia, 2 minutes ago | Successfully approved!! |

## Colour

- Ground every page in `surface`; lift cards to `surface-raised`; sink code and sidebars into `surface-sunk`.
- Set text in `ink`; secondary text in `ink-muted`. Both hold 4.5:1 on all three surfaces in Day and Night.
- Divide with `line`; give controls a `line-strong` edge so they meet 3:1.
- The palette is Mediterranean: cloud white with deep-sea navy ink, and the products take the colours of the island — Amalfi gold for the flagship, then olive, Aegean blue and lavender. Status stays apart: cypress green, tangerine and crimson.
- Night is the Aegean after dark, not an inverted page: grounds go deep navy, ink goes to warm cream, product colours lighten.

### Product colours — the bow tie

| Product | Token | Colour |
| --- | --- | --- |
| Spec Kitty (flagship) | `spec` | Amalfi gold |
| Brain Kitty | `brain` | Olive |
| Build Kitty | `build` | Aegean blue |
| Kitty Factory | `factory` | Lavender |
| Team Kitty | `team` | Amalfi gold — led by Spec Kitty (`team` is an alias of `spec`) |

- Each product has a fill (`spec`), a tinted ground (`spec-soft`) and a text colour (`spec-ink`) for marketing and illustration. If text ever sits on the gold `spec` fill it is `on-spec` (navy); on the other fills it is `on-product`.
- Product colours go on the bow tie, product dots and the cover only — never on buttons, links, selection or status. The `bow` token names the current product's colour: Spec Kitty points it at `spec`, a sister product re-points it at its own, and the kitty follows.
- Actions are product-neutral: `accent` is deep-sea navy by day and cream by night, with `on-accent` on it, in every product. Links are `ink`, underlined.
- Product colours are identity, never status. Don't use `build` to mean "passing" or `factory` to mean "failed".
- Where products appear side by side (a switcher, a docs index), mark each with its colour as a dot beside the name, not as a fill.

### Status colours

- Status has its own set, kept apart from the products by use and always carrying a word or icon — two pairs sit close in hue (gold Spec and Team beside tangerine warning, olive Brain beside cypress success), which is why status never relies on colour alone: `success-*` (done, accepted), `warning-*` (needs attention, waiting on a person), `danger-*` (failed, blocked, destructive).
- Use `*-ink` on `*-soft`. Neutral information is `ink` on `surface-sunk`, not a colour.
- A state that is notable but neither good nor bad (Brain Kitty's *override*, for example) gets no colour of its own: `ink` on `accent-soft`, with its word **and** its icon. The icon matters, because `accent-soft` also carries *in review*.

### Graph role colours

Brain Kitty's knowledge graph colours its nodes by role. The role colours are a third set, kept apart from products and status: the product and status colours leave two open stretches of the wheel — the sea between cypress and Aegean blue, and the bougainvillea between lavender and crimson — and the four roles sit there at four separate lightness steps, so they stay apart for colour-blind readers too.

| Role | Token | Colour | Means |
| --- | --- | --- | --- |
| Frame | `role-frame` | Grotto, deep sea teal | Coordinate axes |
| Selector | `role-selector` | Sea glass, bright aqua | Forking choices |
| Move | `role-move` | Bougainvillea | Patterns and principles |
| Commitment | `role-commitment` | Wax seal, deep plum | Sealed decisions |

- Each role has a colour (`role-frame`) for its sigil, node border and edges, and a tinted ground (`role-frame-soft`) for the node fill or a selected row. Labels on a node are always `ink`.
- The colour never travels alone: every node carries its sigil — ◇ frame, Y selector, ∴ move, ● commitment. The soft grounds pair up (frame with selector, move with commitment), so a soft ground is never the only signal.
- Role colours belong to the graph and the things that point into it (a node chip, a legend). Never use them for products, status, actions or decoration, and never use product or status colours for roles.
- Every role colour holds 3:1 on every surface in Day and Night. `role-selector` only just clears it by day: use it for graphics, never for text.

## Type

- The type is Carta Studio's, so Brain Kitty and the rest of the family read as one house: Newsreader, IBM Plex Sans, IBM Plex Mono.
- Headlines speak in Newsreader (`display`, `title`); the kitty's own words — callout titles — use `quote`, the same serif upright at 20px medium. Never for UI controls or body copy.
- Work gets done in IBM Plex Sans: `heading`, `body`, `small`, `label`.
- Anything a machine also reads — commands, IDs like `WP02`, file paths — is `code` in IBM Plex Mono.
- One `display` per page at most. Keep headlines to one line of thought.
- `label` (13px) is the floor for interface text. The one exception is dense data in the Brain Kitty app: `dense-sm` (12px on 16px) for table cells and graph labels, and `dense-xs` (11px on 14px) for chips and graph annotations. Nowhere else, and never for anything a person must act on.

## Space, shape, depth

- Spacing runs on a 4px base: `space-1` 4 · `space-2` 8 · `space-3` 12 · `space-4` 16 · `space-6` 24 · `space-8` 32 · `space-12` 48 · `space-16` 64.
- Corners are soft but not bubbly: `radius-sm` for badges and inputs, `radius-md` for buttons and callouts, `radius-lg` for cards. `radius-pill` only for pills.
- Borders separate, shadows lift: cards get `line` plus `shadow-1`; floating things get `shadow-2`. No coloured left-border accents.
- Focus is a 2px solid `focus` ring offset 2px from the control.

## The mascot

The kitty is the original drawing (`assets/Origins/naif-kitty.png`), traced line for line into vector. Nothing is redrawn: same outline, ears, three forehead stripes, round glasses joined to the head by their temples, dot eyes, nose and smile, whiskers crossing the cheek line, collar and bow tie, body, paws and tail. The full figure keeps the original's slight turn; the head mark faces straight ahead — the drawing's left half mirrored, with the forehead stripes re-centred. Only the colours are tokens: `kitty-line` (navy) for the line, `kitty-paper` (white) for the fill, the product colour for the bow tie. The kitty is the same white cat in Day and Night — never inverted. On Night grounds it carries a thin white sticker edge, like the original sticker, so whiskers and outlines that leave the face stay visible.

### The family

Every product's kitty is the same traced head — ears, stripes, outline, nose, collar — so they read as one family. Only the bow and a few features change; the new features are drawn in the original's line weight. Each product's eyewear has its own silhouette so the heads stay distinct down to 32px: round wire frames (Spec), tapered rectangles (Brain), oval goggles on a strap (Build). Brain Kitty reads as smart and well-read, never as old — no half-moons, monocles or looking down the nose.

| Product | Glasses | Whiskers | Mouth | Bow |
| --- | --- | --- | --- | --- |
| Spec Kitty | Round wire frames (the original) | Three a side, as drawn | The ":3" smile | `spec` |
| Brain Kitty | Bold, top-heavy acetate frames (a wayfarer shape that tapers slightly to the bottom); eyes look straight through them | Two long, curving | A smaller, quieter smile | `brain` |
| Build Kitty | Protective goggles: soft oval lenses with thick rims, a wide strap and a buckle each side | Three short, straight | An open grin | `build` |
| Kitty Factory | The team: Brain, Spec and Build kitties together, Spec in front | — | — | Each kitty wears its own: `brain`, `spec`, `build` (`factory` lavender is the product's dot and cover) |
| Team Kitty | Kitties with humans, led by Spec Kitty: three people drawn in soft greys behind Spec Kitty, who stands in front | — | — | `team` (Spec's gold) on the kitty; one gold earring |

Rules:

- Use the head for avatars and app icons at 32px and up (`kitty-mark` for Spec Kitty, the product's head for the others); below 32px use the product's glasses alone: `spectacles` for Spec Kitty, `glasses-brain-small` for Brain Kitty.
- Use `kitty-full` for empty states and onboarding, at 120px or larger. The full figure is Spec Kitty's; other products use their head.
- Kitty Factory's team is wider than tall (about 2.3:1): give it at least 96px of width and never crop a side kitty.
- Team Kitty's group is about 1.4:1: give it at least 80px of width. The people stay a step back in soft greys (#545e69, #818991) on white faces so the kitty leads; they are never given a real person's likeness.
- Moods swap only the eyes and mouth, drawn in the same line weight as the original: *attentive* by default, *reading* while something is being reviewed or generated, *thinking* for open questions, *pleased* when something is accepted or shipped, *puzzled* for errors that need a person. Never an angry or sad kitty.
- On Night grounds use the `-night` files (the same white kitty with its sticker edge), or the `Kitty` component, which does this for you. Only `spectacles` switches to cream ink at night, since it has no white fill.
- The bow tie is always the product's colour. Never give a product's kitty another product's bow, or a status colour. Kitty Factory's three kitties each wear their own product's bow. The one shared colour is by design: Team Kitty wears Spec Kitty's gold because Spec Kitty leads it.
- Don't add lines, shading, colour or props beyond a product's own features. Don't put more than one kitty on a screen.
- Give it room: at least `space-4` clear space; never crop the ears.

### App icon

- A rounded square in `surface-raised` white with a `line` edge, on every platform. The tile is never the product colour: the colour stays on the bow.
- On macOS it sits on Apple's grid (an 824px tile on a 1024 canvas, with its shadow inside the canvas); on Windows and Linux the tile fills the canvas.
- The product's head fills 80% of the tile's width, centred, ears clear of the edge.
- At 32px and below the head gives way to the product's glasses on the same tile, drawn to the pixel grid. 48px and up use the head.
- Brain Kitty's files are in `assets/App icon/`.

## Components

`window.SpecKitty` holds `Button`, `Badge`, `Card`, `TextField`, `Callout` and `Kitty` (React 18). Each has its own guideline card. The `GraphRoles` card shows the graph role colours and sigils as nodes; it is a pattern, not a component in the bundle.
