# Button

An action a person takes. **Primary** at most once per view, for the thing the screen is for; **quiet** for everything else; **ghost** for low-stakes navigation-like actions.

- Provide: `variant` (`primary` · `quiet` · `ghost`), `size` (`md` 40px · `sm` 32px), children as a verb-first label in sentence case, plus any native button props.
- Do: "Accept the spec", "Request changes", "Copy command".
- Don't: "Submit", "OK", "Click here", Title Case, icons without a label.
- Primary is `accent` — deep-sea navy by day, cream by night — with an `on-accent` label, in every product. Never paint a button in a product colour; the colour belongs to the bow tie.
