/** Spec Kitty components — window.SpecKitty. React 18. */
export type Mood = 'attentive' | 'reading' | 'thinking' | 'pleased' | 'puzzled';
export type Product = 'spec' | 'brain' | 'build' | 'factory' | 'team';
/** The mascot: always a white cat with a navy line (kitty-paper, kitty-line), with a sticker edge for dark grounds. `product` picks the face and the bow colour; 'factory' is the team of three kitties; 'team' is Spec Kitty in front of three people. */
export function Kitty(props: { mood?: Mood; product?: Product; pose?: 'head' | 'full' | 'glasses'; size?: number; label?: string; className?: string }): JSX.Element;
/** An action. One primary per view. */
export function Button(props: { variant?: 'primary' | 'quiet' | 'ghost'; size?: 'md' | 'sm'; children: React.ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>): JSX.Element;
/** A one- or two-word status, a product name, or a machine key. */
export function Badge(props: { tone?: 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | Product | 'key'; children: React.ReactNode }): JSX.Element;
/** A raised container for one thing: a spec, a work package, a decision. */
export function Card(props: { eyebrow?: React.ReactNode; title?: React.ReactNode; footer?: React.ReactNode; children?: React.ReactNode }): JSX.Element;
/** A labelled input with hint or error. */
export function TextField(props: { label: string; hint?: string; error?: string; mono?: boolean; multiline?: boolean } & React.InputHTMLAttributes<HTMLInputElement>): JSX.Element;
/** The kitty's aside: a note, review, open question, success, warning or problem. */
export function Callout(props: { tone?: 'note' | 'review' | 'question' | 'success' | 'warning' | 'danger'; title?: string; kitty?: boolean; product?: Product; children: React.ReactNode }): JSX.Element;
