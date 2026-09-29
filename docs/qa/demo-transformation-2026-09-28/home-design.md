# Home design working specification

September 28. Agent-selected implementation direction, not user approval of an
industry or scenario. This fixes the confirmed Home-first-impression finding.

Visual thesis: a white, restrained evidence desk with real video as the dominant
visual, dark ink typography, teal actions, and simple dividing rules.
Content: task heading → actual source preview and scoped search → three-step
journey → compact source inventory → local proof and optional environment Q&A.
Interaction: existing video playback controls; clear row hover/focus; disclosure
for advanced Q&A. No ornamental animation or automatic inference.

Built-in Image Gen produced `home-concept.png`. Prompt: full existing desktop
Home with preserved navigation, heading “Find the moment. Understand what
happened.”, real-media placeholder on left, recorded-footage actions on right,
Find/Inspect/Ask-and-share strip, connected-source rows, local processing proof.
No invented incidents or numeric performance claims. Generated warehouse image
is a concept reference ONLY, never footage or an app evidence asset.

Implementation tokens: existing Manrope and Tabler icons; white canvas, ink
#102f34, teal #0c777b, fine neutral borders. Main heading 36px responsive to 28px;
body 15–16px; labels 13px minimum. Media/action grid 2.2:1, 24px gap; media 16:9;
three equal workflow columns; sources as rows. On narrow screens stack media and
actions and workflow steps. Keep existing shell and theme behavior.

Intentional adaptations to the concept: preserve existing shell branding/status;
real runtime source names/counts replace illustrative names; preview uses real
VisionStreamCanvas controls; specific “Find people…” query replaces vague
“Find activity…” to give retrieval a concrete target; local proof opens System;
existing broad environment analyst remains in an optional disclosure. Searchable
means indexed, not proof of retained playback. No claim that paused feeds are live.

Verification: desktop 1440×900 and mobile 390×844; compare hierarchy, media scale,
button treatment, typography, source rows, and copy; real source-scoped search and
playback. Keep screenshots for the requested progress documentation.

## Implemented comparison and verification

- Viewed concept and latest desktop/mobile Playwright screenshots using
  `view_image`. Browser-plugin fallback remains the available Playwright MCP;
  the dedicated Browser plugin was unavailable in the original audit.
- Compared six points: heading hierarchy, real media prominence, 2.2:1 action
  layout, teal primary/outlined secondary actions, three-step divider strip,
  and compact source rows. White surface, existing font, and one accent retained.
- Copy diff: intentional scoped CTA “Find people in this recording”, dynamic
  actual source name/status, and report-specific third-step copy. No added
  performance or incident claims. Existing shell branding/status is preserved.
- Material mismatches fixed: inherited quiet-button rule suppressed the outline;
  inherited player controls sat 154px above the bottom; presentation exit text
  had insufficient contrast in normal and hover states. All three corrected.
- Desktop 1440×900 and mobile 390×844 inspected; mobile has no horizontal
  overflow. Its secondary action continues below the fixed bottom navigation
  and remains reachable by scrolling. Desktop source rows begin below the first
  viewport because actual video uses the specified 16:9 ratio; concept imagery
  was wider. This preserves uncropped evidence rather than its illustrative crop.
- Actual 10-second recording loaded at 1920px width and played/paused. Scoped
  Home search returned HTTP 200 and one matching clip; exact request used
  `people moving`, selected recording name, and `video_file`. System link opened
  the System workspace. No inference is triggered just by opening Home.
- Fidelity: core composition verified against the working concept with the
  documented real-media/shell adaptations. This is one revised surface, not
  final design sign-off for the full application or its content/scenario.
