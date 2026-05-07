# EventTrace — Enhanced Stitch Design Prompt (V2)
> Feed this entire prompt to Stitch. It replaces V1.
> Changes from V1: Snabbit-style color system, 3 new screens (Timeline, Notification Settings, Onboarding),
> filled UX gaps in every existing screen, mobile-first polish throughout.

---

Design a complete UI design system and every screen for a web + mobile app called **EventTrace** — a real-time Calcutta High Court case tracker used by advocates, court staff, and litigants. The app shows live court status (which case is running, which judge is sitting), cause lists (daily hearing schedules), case search, personal case tracking with WhatsApp/SMS alerts, and user profile management.

═══════════════════════════════════════
BRAND & TONE
═══════════════════════════════════════

Product name: EventTrace
Tagline: "Calcutta High Court — Live Tracker"
Logo mark: "ET" bold monogram inside a rounded square, white on violet background
Personality: Crisp, fast, trustworthy. Used under time pressure in a courtroom corridor. Think a modern Indian legal SaaS — data-forward like Bloomberg Terminal but approachable like Snabbit or Zepto. No decorative illustrations. Every pixel earns its place.

═══════════════════════════════════════
COLOR SYSTEM — "Legal Violet" (Snabbit-inspired)
═══════════════════════════════════════

Inspired by modern Indian product design (Snabbit, Zepto): bright violet primary on clean white/near-white surfaces. High contrast. Feels premium, fast, and trustworthy — not government-grey.

Background (page):        #FAFAFA  (off-white, not pure white — easier on eyes)
Surface (cards):          #FFFFFF  (white card)
Surface elevated:         #F5F3FF  (violet-tinted surface, used for selected states)
Border/divider:           #E5E7EB  (gray-200)
Border strong:            #D1D5DB  (gray-300)

Primary action:           #7C3AED  (violet-700)
Primary hover:            #6D28D9  (violet-800)
Primary light bg:         #EDE9FE  (violet-100, for badges and chips)
Primary light text:       #5B21B6  (violet-900)

Success / live:           #16A34A  (green-600)
Success bg:               #DCFCE7  (green-100)
Warning:                  #D97706  (amber-600)
Warning bg:               #FEF3C7  (amber-100)
Error:                    #DC2626  (red-600)
Error bg:                 #FEE2E2  (red-100)

Text primary:             #111827  (gray-900)
Text secondary:           #6B7280  (gray-500)
Text muted:               #9CA3AF  (gray-400)
Text on-primary:          #FFFFFF

Case numbers (mono):      #7C3AED  (violet-700, JetBrains Mono — makes case refs pop)
Tier badge FREE:          #F3F4F6 bg, #6B7280 text
Tier badge PRO:           #FEF3C7 bg, #92400E text (amber)

Sidebar / navbar bg:      #FFFFFF with bottom/right border #E5E7EB
Active nav item bg:       #EDE9FE (violet-100)
Active nav item text:     #7C3AED (violet-700)

═══════════════════════════════════════
TYPOGRAPHY
═══════════════════════════════════════

Font: Inter (primary), JetBrains Mono (case numbers, OTP digits, court IDs)
Scale:
  Page title:     20px / bold / gray-900
  Section header: 11px / semibold / uppercase / letter-spacing 0.1em / gray-500
  Body:           14px / regular / gray-900
  Table cell:     13px / regular / gray-700
  Label:          13px / medium / gray-700
  Caption:        11px / regular / gray-500
  Monospace data: 13px JetBrains Mono / violet-700

═══════════════════════════════════════
DESIGN SYSTEM — COMPONENTS
═══════════════════════════════════════

StatusDot: 8px circle. Live = green-500 with slow pulse (2s). Absent = gray-300 static. Warning = amber-500.

Badge: Pill, 10px semibold, 4px 8px padding. Variants: violet (list type), green (active/live), amber (warning/side), red (absent/error), gray (muted/free).

CourtCard: white card, 1px border gray-200, rounded-xl, 16px padding. Hover: border violet-300, shadow-sm. Left border 3px colored by case type (violet = writ, amber = matrimonial, blue = company, green = criminal). Top row: court number 18px bold left + status dot top-right. Judge row: gray-500 13px. Divider. Case block: case ref violet mono bold, side badge amber, serial muted. Bottom: hearing date + "Join VC" button.

TableRow: 13px. Hover bg violet-50. No zebra. Divider lines only. Focus ring on keyboard nav.

InputField: white bg, 1px border gray-300, focus border violet-500 + violet shadow ring, rounded-lg, 14px, 40px tall. Label above, 13px medium gray-700.

OTPBox: 48×56px square, 1px border gray-300, rounded-lg, center digit mono 24px bold. Focus: violet border + ring. Filled: border violet-500, bg violet-50. Error: border red-500, shake animation.

BottomSheet (mobile): white surface, slides up from bottom, drag handle pill (gray-300, 4px×32px) at top, rounded-t-2xl, 80vh max height, spring animation 300ms.

Modal (desktop): centered overlay, backdrop blur + gray-900/40, white card, rounded-2xl, max-w-md, shadow-xl.

TabBar (bottom, mobile): white bg, top border gray-200, 5 tabs. Active: violet-700 icon (filled) + violet-700 label 10px. Inactive: gray-400 icon + gray-400 label. 64px tall.

NavBar (top, desktop): white bg, bottom border gray-200, 56px tall, sticky. Logo left. Nav tabs center (text links, active = violet-700 + 2px violet underline). Avatar right.

Avatar: circle 32px (navbar) / 64px (profile). Initials white on violet gradient bg. Fallback: gray-300.

Skeleton: gray-100 bg, shimmer animation left-to-right, rounded matching the element it replaces.

ToastNotification: bottom-center, 360px max-w, white bg, left 4px colored stripe (green/red/amber by type), shadow-lg, 14px. Auto-dismiss 4s. Stack vertically if multiple.

ChipFilter: pill button, 32px tall, 12px 16px padding. Default: white bg + gray-300 border + gray-700 text. Active: violet-100 bg + violet-500 border + violet-700 text.

StatCard: white card, rounded-xl, 16px padding. Large number 28px bold gray-900. Label 12px gray-500 below. Accent colored icon top-right.

TimelineItem: left vertical line (gray-200). Circle node (8px, colored by event type). Content right of node. Event type chip. Date muted 11px. Diff block below for UPDATED events.

═══════════════════════════════════════
SCREEN 1: AUTH — STEP 1 (Phone Entry)
═══════════════════════════════════════

Layout: Full-screen #FAFAFA bg. Center card max-w-sm, white, rounded-2xl, shadow-lg, 40px padding.

Top of card:
  — ET logo mark (rounded square 48px, violet-700 bg, "ET" white bold)
  — "EventTrace" 20px bold gray-900
  — "Calcutta High Court — Live Tracker" 13px gray-500

Form below:
  — "Your Name" label + input (placeholder: "Advocate / Staff name") — optional field
  — "Mobile Number" label + input group:
      Left addon: "+91" gray-100 bg, gray-300 border, left-rounded, 13px gray-500
      Right: 10-digit number input, right-rounded, focus violet ring
  — "Send OTP" button: full-width, violet-700 bg, white text, rounded-lg, 44px
  — Error: red-600 text 12px below button

Footer: "By continuing you agree to Terms of Service" — 11px gray-400 centered, "Terms of Service" violet-600 underline link.

Mobile: same, full screen. Keyboard pushes button up via padding-bottom on form container.

═══════════════════════════════════════
SCREEN 2: AUTH — STEP 2 (OTP Verify)
═══════════════════════════════════════

Same card layout.

Top info row (inside card, above OTP):
  — "OTP sent to" gray-500 11px
  — "+91 98765 43210" gray-900 14px semibold
  — "Change number" violet-600 11px underline, right-aligned

Dev mode banner (amber inset card, only in dev):
  — amber-100 bg, amber-600 border-l-4, rounded-lg, 12px padding
  — "Dev Mode — OTP" label amber-600 11px semibold uppercase
  — 6-digit code 28px JetBrains Mono bold amber-700
  — "This banner is hidden in production" 10px amber-500

OTP input row:
  — 6 individual OTPBox squares, gap 8px, centered
  — On digit typed: box bounces (scale 1→1.08→1, 100ms)
  — On fill: border violet-500, bg violet-50
  — On error: red border + horizontal shake animation

Below OTP:
  — "Verify & Sign In" full-width violet button
  — Resend row: "Resend OTP in 45s" gray-400, live countdown. At 0: "Resend OTP" violet underline link. Loading spinner during resend.

═══════════════════════════════════════
SCREEN 3: HOME / DASHBOARD LAYOUT
═══════════════════════════════════════

DESKTOP (> 1024px):
  Sticky navbar 56px, white, bottom border:
    Left: ET logo mark 32px + "EventTrace" 16px semibold gray-900
    Center tabs: [Live Board] [Cause List] [Search] [My Cases]
      Active: violet-700 text + 2px violet underline bottom
      Inactive: gray-500, hover gray-900
    Right: Avatar (32px) + name truncated 14px + tier badge + chevron → dropdown

  Main area: max-w-6xl centered, 24px padding, 24px top.

MOBILE (< 640px):
  Top bar 52px: logo left + avatar right (no tabs)
  Content fills screen
  Bottom tab bar 64px fixed:
    [Board] [Cause List] [Search] [My Cases] [Profile]
    Active: violet filled icon + violet label
    Inactive: gray-400

TABLET (640–1024px):
  Top navbar (same as desktop)
  2-column layouts

═══════════════════════════════════════
SCREEN 4: LIVE BOARD
═══════════════════════════════════════

Page header row:
  — "Live Board" 20px bold left
  — Right: green StatusDot (pulsing) + "Live — updated 12s ago" gray-500 12px
  — Filter chips row: [All] [Sitting] [Absent] [VC Today]

Stats bar (4 StatCards, horizontal scroll mobile):
  — Courts Sitting (violet icon, green accent number)
  — Cases Called (count, gray)
  — Absent Courts (red accent number)
  — VC Available (violet count)

Court grid:
  — Desktop 3-col, tablet 2-col, mobile 1-col
  — Gap 16px

CourtCard (active court):
  — Top row: "Court 12" 18px bold gray-900 + green StatusDot top-right
  — Judge row: gavel icon (14px gray-400) + "Hon'ble Justice A. K. Rao" gray-600 13px
  — Divider gray-100
  — Case block:
      "WP/12345/2026" violet mono bold 14px (full width)
      Below: "PETITIONER'S SIDE" amber badge (left) + "#42" gray-400 (right)
      Below: "Daily" gray badge + "Hearing: 05 May 2026" gray-400 11px
  — Bottom row: "05 May 2026" gray-400 11px left + "Join VC" violet outline button 28px right (only if VC link exists)
  — Left border 3px: violet (writ/WP), amber (matrimonial/MAT), blue (company/CP), green (criminal/CRR)

CourtCard (absent court):
  — Same card, opacity 50%
  — Center overlay: "NOT SITTING" red-500 13px semibold, gray-400 subtext "No bench today"
  — No VC button

Flash animation: when data updates, card border briefly pulses violet (0→1→0 opacity, 600ms).

Card click → CourtDetail panel:
  Desktop: right side panel 360px slides in, pushes grid
  Mobile: BottomSheet slides up

CourtDetail content:
  — Header: "Court 12 — Today's Activity" + close X
  — Timeline list (newest first):
      Each row: time (HH:MM) gray-400 | "#42" | "WP/12345/2026" violet mono | "Pet. Side" badge | duration chip "4m 23s" gray
  — If no events yet: "No cases called yet today" centered gray-400

═══════════════════════════════════════
SCREEN 5: CAUSE LIST PAGE
═══════════════════════════════════════

DESKTOP: Two-panel layout

Left panel (280px fixed, white bg, right border):
  — "Cause List" 16px semibold + date dropdown right-aligned (shows available dates, most recent first, YYYY-MM-DD display)
  — Side filter chips: [Appellate] [Original] — pill chips below header
  — List type chips: [Daily] [Monthly] [Special] — second row
  — Court list scrollable:
      Each row 48px: "Court 1" 14px semibold gray-900 + bench label 11px gray-500 below + case count badge right
      Selected: violet-100 bg + violet-700 left border 3px
      NOT SITTING: "NOT SITTING" red-500 11px right, row muted opacity 60%
      Hover: gray-50 bg

Right panel (flex-1):
  Empty state: centered, scales-of-justice outline icon gray-200 48px, "Select a court to view cases" gray-400 14px
  
  Court selected state:
    Panel header (sticky, white, bottom border):
      — "Court 1 — Daily List" 16px bold
      — "Bench: Division Bench" gray-500 13px
      — "Hon'ble Justice X, Hon'ble Justice Y" gray-600 13px
      — Case count: "42 cases" violet badge right
    
    Cases table (sticky column headers):
      Columns: [#] [Case Ref] [Petitioner] [Respondent] [Advocate] [Actions]
      Header: 11px uppercase gray-500 semibold, gray-50 bg
      Row: 13px, 40px tall, hover violet-50 bg
      Case ref: violet mono 13px
      Long text: truncate with ellipsis + tooltip on hover
      Actions column (appears on row hover): star icon button "Track" + info icon "Details"
      Row click: expand inline row with full details OR open CaseDetail modal

  Empty results state: "No cases found for this court and date" gray-400 centered

MOBILE: Full-screen drill-down
  Screen A (courts list): same as left panel but full width, back button top-left
  Screen B (cases list): full width table, back button "← Court 1" top-left, swipe-right to go back

═══════════════════════════════════════
SCREEN 6: SEARCH PAGE
═══════════════════════════════════════

Search inputs:
  Desktop: 3 inputs in row + Search button
  Mobile: stacked full-width + Search button

  Inputs:
    — "Advocate name..." (placeholder)
    — "Party / petitioner..." 
    — "Case Ref  e.g. WP/123/2026" (monospace placeholder)
  
  Date range row (collapsed by default, "Filter by date ▼" gray link to expand):
    — "From" date picker + "To" date picker
    — Side filter: [Appellate] [Original] pill chips
    — List type filter: [Daily] [Monthly] pill chips

Search button: violet-700, 44px, "Search", full-width mobile.

No query state: centered search icon gray-200 + "Search by advocate, party, or case number" gray-400.

Loading state: skeleton rows (5 rows, varying widths).

Results header: "34 results" gray-500 12px left + "Sorted by date, newest first" 11px right.

Results table:
  Columns: Date | Court | # | Case Ref | Petitioner | Advocate | (Actions)
  Case ref: violet mono
  Date: relative if same week ("Mon 28 Apr") else full
  Actions column: star icon "Track" — appears on row hover (desktop), always visible (mobile)
  Row click → CaseDetail modal / bottom sheet

No results state: search-slash icon gray-200 + "No cases found. Try different search terms." gray-400.

Pagination: "Load 50 more" violet text button centered below results.

═══════════════════════════════════════
SCREEN 7: MY CASES (Personal Dashboard)
═══════════════════════════════════════

Page header:
  — "My Cases" 20px bold left
  — "Track a Case" violet button right (+ icon)

Empty state (no cases tracked):
  — Bookmark outline icon gray-200 64px centered
  — "No tracked cases yet" 16px semibold gray-900
  — "Track cases to get alerts when they appear in the cause list" 14px gray-500
  — "Track Your First Case" violet button 44px

Tracked cases list (card per case):
  — Case ref: violet mono bold 16px (full width top)
  — Row below: court badge gray + case type badge violet + next hearing date (calendar icon + date, green if upcoming, gray if past)
  — "Last seen: Mon 28 Apr, Court 5, Serial #42" gray-500 12px with clock icon
  — Alert status row:
      Alert active: green StatusDot + "WhatsApp alert — Serial ≥ 39 (buffer 3)" green-600 12px semibold
      No alert: gray StatusDot + "No alert set" gray-400 12px
  — Action buttons row: [Edit Alert] outline gray button + [View Timeline] outline violet button + [Remove] outline red button — 32px tall, 11px
  — Card: white bg, rounded-xl, 1px border gray-200, 16px padding, hover shadow-sm

Track Case modal / bottom sheet:
  Title: "Track a Case" 16px bold
  Fields:
    — "Case Reference *" label + monospace input (placeholder: WP/12345/2026, violet text on type)
    — "Court Number" dropdown (1–40)
    — "Label (optional)" input (placeholder: "e.g. My Land Dispute")
    — "Set alert" toggle (violet toggle, off by default)
    — If toggle on (expand section):
        — "Alert when court reaches serial #" + number input stepper (violet +/- buttons)
        — "Notify me X serials before" + stepper (default 3)
        — "WhatsApp number" +91 input (pre-filled from profile, editable)
        — Preview inset: violet-50 bg, "You'll be alerted when Court X reaches approximately serial Y" 12px violet-700
  Actions: [Cancel] gray text button + [Save & Track] violet full-width button

═══════════════════════════════════════
SCREEN 8: CASE TIMELINE (NEW SCREEN)
═══════════════════════════════════════

Reached via "View Timeline" button on a tracked case card, or URL /case/:case_ref.

Header:
  — Back arrow + "WP/12345/2026" violet mono 18px bold
  — "Tracking since 01 Apr 2026" gray-500 12px
  — [Set Alert] violet outline button right

Stats row (3 small stat cards):
  — "Days tracked" count
  — "Times appeared" count (green)
  — "Changes detected" count (amber)

Timeline (vertical, newest first):
  Left: continuous gray-200 line. Node circles colored by event type.

  Event types:
    TRACK_STARTED node: violet circle. Chip "Tracking started" violet badge. "You added this case" gray-500.
    
    NO_CHANGE node: gray circle. "No changes" gray badge. Date + "Court 5, Serial #42 — same as before" gray-400 12px.
    
    UPDATED node: amber circle. "Updated" amber badge. Date below.
      — Expandable diff block (open by default on most recent UPDATED):
          Each changed field: gray-900 label + "Old value → New value" layout
          Old: red-100 bg, red-600 strikethrough text
          New: green-100 bg, green-600 text
          e.g. "Advocate: Ravi Kumar → Suresh Pal"
          e.g. "Court: 5 → 7"
    
    NOT_FOUND node: red circle. "Not listed" red badge. "This case did not appear in the cause list on this date" gray-400 12px.

  Load more: "Load older events" gray text button at bottom.

Empty state (just started tracking): "Tracking started. Timeline will update after the next cause list is published." gray-400 centered.

═══════════════════════════════════════
SCREEN 9: CASE DETAIL MODAL
═══════════════════════════════════════

Opens as Modal (desktop) or BottomSheet (mobile). Max-w 560px.

Header:
  — "WP/12345/2026" violet mono 20px bold
  — "Court 5 — 28 Apr 2026" gray-500 13px below
  — [Track This Case] violet button top-right (becomes gray "Tracking" if already tracked)
  — Close X top-right corner

Tabs: [Details] [History] — violet underline on active

Details tab:
  Two-column grid (label left, value right):
    Petitioner:    [full name]
    Respondent:    [full name]
    Advocate(s):   [comma separated]
    Serial No.:    [#42]
    List Type:     [Daily badge]
    Hearing Date:  [05 May 2026]
    Court:         [Court 5]
    Side:          [PETITIONER'S SIDE amber badge]
    IA Numbers:    [IA/123/2026, IA/124/2026] or — if none
  
  If tracked: green StatusDot + "You are tracking this case" green-600 12px at bottom

History tab:
  — "All appearances in cause list" gray-500 12px header
  — Table: Date | Court | # | Side | List Type
  — Newest first
  — Each row: date + court (violet-700 mono) + serial + side badge + list type badge
  — Empty: "No history found. This case may be new or search data unavailable."

═══════════════════════════════════════
SCREEN 10: ALERT SET MODAL
═══════════════════════════════════════

Triggered from: tracked case card "Edit Alert" OR cause list row "Set Alert".
Modal (desktop) / BottomSheet (mobile).

Title: "Set Hearing Alert" 16px bold
Subtitle: "WP/12345/2026" violet mono 13px below title

Fields:
  — "Court / Room" dropdown (pre-filled if known, editable)
  — "Hearing Date" date picker (pre-filled if known)
  — "Alert me when court reaches serial #" + stepper input (violet +/- buttons, 1–999)
  — "Notify me ___ serials before" + small stepper (default 3, range 0–20)
  — "WhatsApp Number" +91 + 10-digit input (pre-filled from profile)

Live preview card (violet-50 bg, violet-200 border, 12px padding, rounded-lg):
  "You will be alerted on WhatsApp (+91 98765 43210) when Court 5 reaches approximately serial 39 (alert at serial 42, buffer 3)"
  Updates live as user changes inputs.

Actions:
  — [Cancel] gray text button
  — [Set Alert] violet full-width button 44px

Success state (after save): card briefly flashes green, "Alert set!" toast appears bottom-center.

═══════════════════════════════════════
SCREEN 11: PROFILE PAGE
═══════════════════════════════════════

MOBILE: Full page (bottom tab "Profile")
DESKTOP: Dropdown panel (320px wide, right-aligned from avatar, shadow-xl, rounded-xl)

Profile header:
  — Avatar 64px circle, initials white on violet gradient
  — Name 18px bold gray-900 (inline editable — pencil icon appears on hover)
  — Phone gray-500 13px (non-editable)
  — Tier badge row: FREE or PRO pill + "Upgrade to Pro" amber button (amber-600 text, amber-100 bg, if FREE)

Edit mode (name / email):
  — Field turns into input with violet focus ring
  — [Save] violet button + [Cancel] gray text button appear
  — Saving: spinner in button

Sections (divider between each):
  "ACCOUNT" section header (11px uppercase gray-400):
    — "Notification Settings" row: bell icon + label + → arrow. Click → Notification Settings screen
    — "Tracked Cases" row: bookmark icon + "4 cases tracked" + → arrow. Click → My Cases
    — "Email" row: editable inline, pencil icon

  "SUPPORT" section:
    — "Terms of Service" → external link icon
    — "Privacy Policy" → external link icon
    — "Help / Feedback" → external link icon

Danger zone (bottom, separated by red-100 divider):
  — "Sign Out" button: full-width, red-50 bg, red-600 text, red-200 border, rounded-lg, 44px
  — Tap → confirm dialog: "Sign out of EventTrace?" gray card, [Cancel] + [Sign Out] red button

═══════════════════════════════════════
SCREEN 12: NOTIFICATION SETTINGS (NEW SCREEN)
═══════════════════════════════════════

Reached from Profile → Notification Settings.

Header: ← back arrow + "Notification Settings" 16px bold

Sections:

"CHANNELS" section:
  — WhatsApp row: whatsapp icon green + "WhatsApp" label + toggle (violet) + "+91 98765 43210" gray-500 12px below toggle. If off: grayed number.
  — Email row: mail icon + "Email" label + toggle + email address below. If not set: "Add email" violet link.
  — Tap channel row → edit phone/email inline

"ALERT TYPES" section:
  — "Case appears in cause list" toggle — notify when tracked case appears in any future list
  — "Court serial alert" toggle — notify when court reaches target serial (live board)
  — "Case details changed" toggle — notify when tracked case has changes vs last snapshot

"TEST" section:
  — "Send test WhatsApp" violet outline button — sends test message to configured number
  — Status: last test "Sent 2m ago ✓" gray-400 11px

DLT status banner (amber, if MSG91 DLT pending):
  — amber-100 bg, amber-600 border-l-4
  — "WhatsApp delivery pending regulatory approval (DLT). Alerts will activate once approved."
  — "Expected: 3–7 business days" amber-600 11px

═══════════════════════════════════════
SCREEN 13: ONBOARDING (NEW — first-time user)
═══════════════════════════════════════

Shown once after `is_new_user = true` from verify-otp response. 3 swipeable cards.

Card 1:
  — Gavel icon 48px violet-700 centered
  — "Live Court Status" 18px bold
  — "See which case is running in every courtroom, right now." gray-500 14px
  — Progress: ●○○

Card 2:
  — Bell icon violet
  — "Get Hearing Alerts" 18px bold
  — "Track your cases. Get a WhatsApp message before your serial is called." gray-500 14px
  — Progress: ●●○

Card 3:
  — Search icon violet
  — "Search Any Case" 18px bold
  — "Find cases across the full cause list by advocate, party, or case number." gray-500 14px
  — Progress: ●●●
  — "Get Started" violet full-width button

Skip link: "Skip" gray-400 underline top-right on all cards.

═══════════════════════════════════════
NAVIGATION COMPONENTS
═══════════════════════════════════════

Desktop Navbar (design in isolation):
  — 56px tall, white bg, border-b gray-200, sticky top
  — Left: ET logo mark 32px + wordmark "EventTrace" 16px semibold
  — Center: tabs — [Live Board] [Cause List] [Search] [My Cases]
      Active tab: violet-700 text + 2px violet-700 border-bottom
      Inactive: gray-500 hover:gray-900, 14px
      Tab spacing: 8px padding-x each
  — Right: avatar 32px + name 14px truncated max-w-[120px] + tier badge + chevron
      Avatar click → dropdown menu (Profile / Notification Settings / Sign Out)

Mobile Bottom TabBar (design in isolation):
  — 64px tall, white bg, border-t gray-200, fixed bottom, safe-area-inset
  — 5 tabs equal width: [Board] [Cause List] [Search] [My Cases] [Profile]
  — Active: filled violet icon 22px + violet-700 label 10px semibold
  — Inactive: outline gray-400 icon + gray-400 label
  — Tap: icon does small bounce (scale 1→1.15→1, 150ms spring)

Mobile Top Bar:
  — 52px, white bg, border-b gray-200
  — ET logo mark 28px left + "EventTrace" 14px semibold
  — Avatar 32px right (tap → Profile page)

═══════════════════════════════════════
INTERACTIONS & MICRO-ANIMATIONS
═══════════════════════════════════════

— Live Board cards: on data update, left border flashes violet (0→full→0 opacity, 600ms ease-out)
— OTP boxes: each digit typed → scale 1→1.08→1 (100ms). Wrong OTP → shake left-right (400ms).
— StatusDots on live courts: opacity pulse 1→0.4→1, 2s ease-in-out loop
— Page transitions: fade + 8px slide-up (150ms ease-out)
— Bottom sheets: spring slide-up 300ms (cubic-bezier 0.34, 1.56, 0.64, 1)
— Tab bar tap: icon bounce scale 1→1.15→1, 150ms spring
— Button loading: spinner (violet) replaces text, disabled. Minimum 400ms so it doesn't flash.
— Toggle: smooth slide 200ms ease
— CourtCard hover: border transitions to violet-300, shadow appears (200ms)
— Skeleton shimmer: gradient left-to-right animation, gray-100 → gray-50 → gray-100, 1.5s loop
— Toast: slide up from bottom 200ms, auto-dismiss after 4s with fade-out
— Timeline UPDATED diff: expand/collapse with smooth height animation 200ms
— Track button: on click, star icon fills violet with pop scale 1→1.3→1

═══════════════════════════════════════
RESPONSIVE BREAKPOINTS
═══════════════════════════════════════

Mobile (< 640px):
  — Bottom tab bar navigation (5 tabs)
  — Single column layouts
  — BottomSheets replace modals
  — Cause list: full-screen drill-down (courts → back → cases)
  — Court cards: full width, compact
  — Search: stacked inputs
  — Stats: horizontal scroll row

Tablet (640–1024px):
  — Top navbar
  — 2-column court grid
  — Cause list: 2-panel (left panel collapsible)
  — Modals (not bottom sheets)

Desktop (> 1024px):
  — Top navbar, max-w-6xl centered
  — 3-column court grid
  — CourtDetail: right side panel (not bottom sheet)
  — Hover states on all interactive elements
  — Keyboard navigation support

═══════════════════════════════════════
EMPTY & ERROR STATES
═══════════════════════════════════════

Live Board — no data:
  — Skeleton grid of 6 CourtCard ghosts
  — After 10s still loading: "Having trouble connecting. Check your network." red toast

Live Board — court data stale (no update > 2 min):
  — Top banner: amber-100 bg "Data may be outdated — last updated X minutes ago"

Cause List — no date available:
  — Centered calendar icon gray-200 + "No cause lists available yet. Lists are published by 10 PM." gray-400

Cause List — court NOT SITTING:
  — Right panel shows: "Court 5 is not sitting today" red-500 centered + gray-400 "No bench assigned"

Search — no query entered:
  — Centered magnifying glass gray-200 + "Search by advocate, party name, or case number" gray-400

Search — no results:
  — Search-slash icon gray-200 + "No cases match your search" gray-900 14px + "Try different keywords or expand the date range" gray-400 12px

My Cases — empty:
  — Bookmark outline icon gray-200 64px + copy described above

Case Timeline — no events yet:
  — "Tracking started. Check back after the next cause list is published." gray-400 + calendar icon

Network error:
  — Toast bottom-center: red-600 left stripe, "Connection lost — retrying" gray-900 14px, animated retry spinner

Auth wrong OTP:
  — All OTP boxes red border + shake animation + "Incorrect OTP. X attempts remaining." red-600 12px below

Auth expired OTP:
  — "OTP has expired." red-600 + "Resend OTP" violet link appears immediately

Session expired:
  — Toast: "Session expired — please sign in again" amber warning, then redirect to AuthPage after 2s

═══════════════════════════════════════
SCREENS TO DESIGN (complete list)
═══════════════════════════════════════

1.  Auth Step 1 — Phone entry (mobile + desktop)
2.  Auth Step 2 — OTP verify with dev mode amber banner (mobile + desktop)
3.  Onboarding — 3-step swipeable cards (mobile)
4.  Live Board — active courts grid, various card states: active, absent, VC today (desktop 3-col + mobile 1-col)
5.  Live Board — CourtDetail right panel (desktop) + BottomSheet (mobile) with today's timeline
6.  Cause List — two-panel, court selected, cases table visible (desktop)
7.  Cause List — mobile drill-down: Screen A courts list + Screen B cases list
8.  Search — results populated, hover state showing Track button (desktop)
9.  My Cases — 2 tracked cases (1 with alert set, 1 without), empty state variant (mobile)
10. Case Timeline — full timeline with TRACK_STARTED + NO_CHANGE + UPDATED (with diff) + NOT_FOUND events (mobile)
11. Case Detail Modal — Details tab + History tab (desktop modal + mobile bottom sheet)
12. Alert Set Modal — with live preview card (desktop modal + mobile bottom sheet)
13. Profile — full page (mobile) + dropdown panel (desktop)
14. Notification Settings — full page (mobile)
15. Navigation: desktop navbar (standalone) + mobile bottom tab bar (standalone) + mobile top bar

═══════════════════════════════════════
COLOR THEME OPTIONS
═══════════════════════════════════════

Option A: "Legal Violet" (recommended — described above)
Clean white + violet primary. Snabbit/Zepto-inspired. Modern Indian product aesthetic. Professional but fast-feeling.

Option B: "Slate Dark" (original V1 request)
Deep navy #0F172A + indigo primary. Bloomberg Terminal aesthetic. No light mode.

Option C: "Legal Green"
White + emerald-600 primary. Associates with justice/law/money. Calmer than violet.

Designer's recommendation: Option A for mobile-first (easier in daylight), Option B for power users who stare at it all day.

---
