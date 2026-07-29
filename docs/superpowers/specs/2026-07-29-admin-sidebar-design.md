# Admin Sidebar Design

## Goal

Update the authenticated admin sidebar to match the provided visual direction while preserving every existing route and permission gate.

## Layout

- Keep a fixed, 220px desktop sidebar within the existing application shell.
- Add a branded header with the product name and subtitle.
- Keep navigation in the center and place a compact current-user block at the bottom.
- Preserve the existing responsive behavior: at narrow widths, the sidebar becomes a full-width top section.

## Navigation

- Attach a 16px line icon to each visible route without changing route hashes, labels, or permission checks.
- Use 14px menu labels, 36px item height, and an 8px radius.
- Apply a pale blue background and blue foreground to the active route; use muted blue-gray for inactive routes.
- Use inline SVG icon components to avoid adding a dependency for this scoped visual-only change.

## Verification

- Run the admin production build.
- Confirm the desktop sidebar renders with the new header, icons, selected state, and user block.
- Confirm the narrow responsive layout continues to use a single-column application shell.
