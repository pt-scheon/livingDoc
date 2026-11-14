# LivingDoc design system

Direction: **Neel & Haldi, calmed down.** It keeps the brand you already have (indigo-dye ink with a turmeric highlight) and makes it a quiet, paper-like workspace that a shop owner can read at a glance in English, Hindi or Gujarati. Deep indigo carries trust and structure; haldi (turmeric yellow) is the one warm signal, used sparingly so it always means "look here". Covers both LivingDoc (stock and accounts) and Foresight (demand forecast), which share one shell.

Rules of thumb:
- One primary action per screen. Everything else is secondary or quiet.
- Borders separate things; shadows are only for things that float.
- Numbers are the hero: big, tabular, never decorated.
- No gradients, no glass, no emoji icons, no gradient text.

## Color

All tokens live in `frontend/css/tokens.css`. Pages use the names, never raw hex.

| Token | Light | Dark | Role |
|---|---|---|---|
| `--bg` | #f6f7fb | #0a0f2e | Page background |
| `--paper` | #ffffff | #131a47 | Cards, panels, inputs |
| `--paper-2` | #f5f6fb | #19215a | Table stripes, hover rows, wells |
| `--line` | #dde1ee | #28316e | Borders and dividers |
| `--ink` | #12183a | #eef0ff | Headings and body text |
| `--ink-2` | #4f5677 | #a9b1da | Secondary text, labels |
| `--ink-3` | #6b7192 | #8590c4 | Hints, placeholders, disabled text |
| `--accent` | #2b3a9e | #93a4ff | Primary buttons, links, focus, selected nav |
| `--accent-hover` | #22307f | #aab7ff | Primary button hover |
| `--accent-ink` | #ffffff | #0a0f2e | Text on `--accent` |
| `--accent-soft` | #e5e8fb | #232d6b | Selected row, quiet button hover, forecast band |
| `--haldi` | #f2b01e | #f6bd3c | The one accent: today marker, "needs attention" badge, key highlight. Max one per view |
| `--haldi-ink` | #3b2a00 | #3b2a00 | Text on `--haldi` |
| `--side` | #121a4a | #080c25 | Sidebar / top bar |
| `--side-ink` / `--side-dim` | #dfe4ff / #98a1d6 | same | Sidebar text, active / inactive |
| `--ok-bg` / `--ok-fg` | #dcf3e6 / #11573a | #123b2c / #a6e8c4 | Success, "in stock" |
| `--low-bg` / `--low-fg` | #fdf0c8 / #6f4604 | #4a3a0c / #f6d98a | Warning, "low stock" |
| `--out-bg` / `--out-fg` | #fbdcdf / #8d1c2a | #4b1a26 / #f7b4be | Error, "out of stock", destructive |
| `--info-bg` / `--info-fg` | #e3e9fb / #1f3377 | #1c2766 / #bccaff | Info notes, sync status |

Charts: actuals `--chart-actual` (ink-2), forecast line `--chart-forecast` (accent), confidence band `--chart-band` (accent-soft), today marker `--haldi`.

Contrast checked: body text 16:1, secondary 6.7:1, hint 4.8:1, accent on white 9.5:1, all status pairs above 7:1, in both modes.

## Typography

- **Headings:** Bricolage Grotesque 600/700 (fallback Noto Sans for Devanagari and Gujarati).
- **Body and UI:** Noto Sans 400/500/600, with Noto Sans Devanagari and Noto Sans Gujarati.
- **Numbers:** `font-variant-numeric: tabular-nums` on all money, stock counts and tables.
- **Mono:** system mono, only for SKUs, IDs and codes.
- Body text is never below 16px (Indic scripts need the room). Lines 60–75 characters (`--measure: 68ch`).

| Token | Size / line height | Use |
|---|---|---|
| `--text-xs` | 12 / 16 | Badges, chart axis labels |
| `--text-sm` | 14 / 20 | Table meta, helper text |
| `--text-md` | 16 / 24 | Body, inputs, buttons |
| `--text-lg` | 18 / 28 | Lead paragraph, card titles |
| `--text-xl` | 22 / 30 | Section headings |
| `--text-2xl` | 28 / 36 | Page title |
| `--text-3xl` | 36 / 44 | KPI numbers |
| `--text-4xl` | 48 / 56 | Landing hero only |

## Spacing and layout

4px base: `--space-1` 4, `--space-2` 8, `--space-3` 12, `--space-4` 16, `--space-5` 24, `--space-6` 32, `--space-7` 48, `--space-8` 64.

- Inside cards: `--space-5`. Between cards: `--space-4`. Between page sections: `--space-7`.
- Content width `--content: 1120px`; reading width `--measure: 68ch`.
- Layouts are left-aligned. Center only the login card and empty states.

## Shape and depth

- Radius: `--radius-xs` 6 (badges, chips), `--radius-sm` 10 (buttons, inputs), `--radius` 16 (cards, panels), `--radius-pill` 999 (toggles, avatars).
- Shadows: `--shadow` hairline for resting cards (none in dark mode), `--shadow-lift` only for menus, dialogs and toasts.

## Components

- **Buttons** (height 40, `--text-md`, `--radius-sm`):
  - Primary: `--accent` fill, `--accent-ink` text, hover `--accent-hover`.
  - Secondary: `--paper` fill, `--line` border, `--ink` text, hover `--paper-2`.
  - Quiet: no fill, `--accent` text, hover `--accent-soft`.
  - Destructive: `--out-fg` text on secondary style; filled only inside a confirm dialog.
  - Focus: 2px `--focus` ring, 2px offset. Disabled: `--ink-3` text, `--paper-2` fill, no hover.
- **Links:** `--accent`, underline on hover and always inside body text.
- **Inputs:** height 40, `--paper` fill, `--line` border, `--radius-sm`; focus border `--accent` plus ring; error border `--out-fg` with message below in `--text-sm`.
- **Cards:** `--paper`, 1px `--line`, `--radius`, `--shadow`. One title, one main number or table. No coloured top bars.
- **KPI tile:** label `--text-sm` `--ink-2`, value `--text-3xl` tabular, change as a status chip.
- **Status chips:** `--radius-xs`, `--text-xs` 600, the matching `*-bg` / `*-fg` pair. Always text plus color, never color alone.
- **Tables:** 48px rows, `--line` dividers, `--paper-2` hover, numbers right-aligned.
- **Navigation:** `--side` sidebar on desktop, bottom tab bar on mobile; active item `--side-ink` with a 3px `--haldi` bar, inactive `--side-dim`. Language switcher (EN / हि / ગુ) always in the top bar.
- **Footer:** one line, `--text-sm` `--ink-3`.
- **Toasts:** `--paper`, `--shadow-lift`, status chip on the left, auto-hide after 4s.

## Imagery and icons

- Icons: Lucide, 20px, 1.75 stroke, `currentColor`. No emoji as icons.
- No stock photos. Show the real product: screenshots of the dashboard and forecast inside a `--radius` frame with a `--line` border.
- Signature motif: the haldi dot grid, used only on the login screen and empty states, at low opacity. Nowhere else.
