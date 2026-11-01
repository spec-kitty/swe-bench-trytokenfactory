# Graph roles

How Brain Kitty's knowledge graph shows a node's role: a sigil in the role colour, a border in the role colour, a `role-*-soft` fill and an `ink` label.

- Provide per node: its role (`frame` · `selector` · `move` · `commitment`), its sigil (◇ diamond outline, Y fork, ∴ three dots, ● disc) and a short label in sentence case.
- Edges take the colour of the node they leave, at reduced opacity, 1.5px.
- Never show a role by colour alone, never put role colours on controls, products or status, and never set text in `role-selector`.
- This is a pattern, not a bundled component: build it with the `role-*` tokens.
