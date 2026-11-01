# Kitty

The mascot drawn inline: always a white cat with a navy line (`kitty-paper`, `kitty-line`) and its bow tie in the product colour. It is never inverted for Night; a thin white sticker edge keeps whiskers and outlines readable on dark grounds. The `glasses` pose, which has no fill, uses `ink` and so turns cream at night.

- Provide: `mood` (`attentive` default · `reading` · `thinking` · `pleased` · `puzzled`), `pose` (`head` default · `full` · `glasses`), `product` (`spec` · `brain` · `build` · `factory` · `team`; omit it for Spec Kitty's face with the `bow` colour), `size` in px (width), and `label` for its accessible name (empty string when decorative).
- `product` picks the face as well as the bow: Brain Kitty wears bold, top-heavy acetate frames, Build Kitty wears oval protective goggles on a buckled strap, Kitty Factory is the team of three, each in its own product's bow; Team Kitty is Spec Kitty in front of three people.
- `head` from 32px, `full` from 120px (Spec Kitty only); under 32px use `glasses`, which draws the product's own frames: Spec Kitty's round spectacles, or Brain Kitty's acetate frames with `product="brain"`. Kitty Factory from 96px wide, Team Kitty from 80px wide.
- One kitty per screen (the Factory team counts as one). Never angry, never sad, never in costume; moods change only the eyes and mouth.
