# Design Guidelines

This file defines the visual and UX reference for the `design/` SwiftUI mockups.

## Scope
- Applies to:
  - `design/CrewPortalDashboard.swift`
  - `design/CrewLinkLoginView.swift`
- Goal:
  - Keep a consistent, production-like mobile-first UI language.

## Core Style
- Theme:
  - Default dark UI.
  - High-contrast foreground text.
  - Muted secondary text for metadata.
- Mood:
  - Aviation ops dashboard: clean, efficient, data-dense.
- Layout:
  - Mobile-first composition.
  - Desktop/tablet uses split-pane only when space allows.

## Color System
- Primary action: `#136DEC`
- Background dark: `#101822`
- Surface dark: `#192433` to `#1C2633`
- Surface highlight: `#233348`
- Secondary text: desaturated blue-gray
- Status colors:
  - Success/operational: green
  - Warning/pending: amber/orange
  - Neutral indicators: slate/gray

## Typography
- Preferred families:
  - Display: Manrope
  - Body: Noto Sans
- If unavailable:
  - Fallback to SF system fonts with weight hierarchy preserved.
- Hierarchy:
  - H1/Hero: bold/black
  - Section titles: semibold/bold
  - Metadata labels: small uppercase or semibold small text

## Spacing and Shape
- Base spacing rhythm:
  - 8pt grid
  - Typical paddings: 12, 16, 24, 28
- Corner radius:
  - Inputs/buttons/cards: 10-12
  - Pills/chips: capsule
  - FAB: circle
- Borders:
  - 1px subtle border on dark surfaces for separation.

## Components
- Cards:
  - Collapsible sections for dense dashboard content.
  - Header row + optional expanded body.
- Buttons:
  - Primary: filled primary blue, bold white label.
  - Secondary: surface background + subtle border.
- Inputs:
  - Left icon + text field/secure field.
  - Focus state should emphasize primary color ring.
- Navigation:
  - Bottom tab bar with centered floating action button on dashboard.

## Iconography
- SwiftUI implementation uses SF Symbols.
- Material Symbols can be used only if added as custom assets/fonts.
- Keep icon stroke weight visually consistent across screens.

## Imagery
- Use high-quality aviation imagery for hero/background.
- Avatars and crew photos:
  - Circular crop
  - Optional border ring in primary color for identity emphasis.

## Motion
- Keep motion subtle and functional:
  - Disclosure expand/collapse: short ease-in-out.
  - Avoid decorative-heavy animation.

## Accessibility
- Maintain readable contrast in dark mode.
- Minimum tap target: 44x44.
- Avoid color-only meaning; pair with text labels where possible.

## Authentication UX (Google OAuth)
- Google button is first-class action at top of auth card.
- Show explicit loading state while OAuth sheet is in progress.
- Show clear success/error message after OAuth completion.
- Keep email/password flow available as fallback UI when needed.

## Engineering Notes
- Reuse shared theme tokens (colors, spacing intent) across files.
- Keep auth logic separate from view code:
  - `design/Auth/GoogleSignInManager.swift`
  - `design/Auth/GoogleAuthConfig.swift`
- Do not hardcode secrets in source.
- Read OAuth identifiers from app configuration (`Info.plist`).
