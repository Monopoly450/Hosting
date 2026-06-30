# ByteBurners Hosting UI - Design System

## Theme Settings
- Base Theme: Light Mode Only (No dark mode).
- Aesthetic: Premium, Modern, Clean.
- Style: Apple-like minimalism with subtle glassmorphism for overlays and cards.

## Color Palette
- Primary Action: Bright Electric Blue (#007AFF or #2563EB).
- Secondary: Soft Gray / Slate.
- Background: Very light gray or off-white (#F9FAFB) to make white cards pop.
- Cards/Containers: Pure White (#FFFFFF) with very subtle shadows (e.g. `box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05)`).
- Text Primary: Dark Slate (#111827).
- Text Secondary: Gray (#6B7280).
- Borders: Extremely subtle light gray (#E5E7EB).
- Status Colors:
  - Success: #10B981
  - Warning: #F59E0B
  - Danger: #EF4444

## Typography
- Font Family: 'Inter', 'SF Pro Display', sans-serif.
- Headings: Bold, clean, good letter-spacing.
- Body: 14px or 15px for readability, with 1.5 line height.

## UI Elements
- **Cards**: Rounded corners (e.g., 12px or 16px radius), white background, subtle drop shadow.
- **Buttons**:
  - Primary buttons should be solid blue, rounded corners (8px radius).
  - Secondary buttons should be outline or light gray background.
  - Interactive states: Hover effects should slightly lift the button or darken the background.
- **Glassmorphism**: For modals and floating panels, use a semi-transparent white background (`rgba(255, 255, 255, 0.8)`) with `backdrop-filter: blur(12px)`.
- **Inputs**: Clean borders, slightly rounded, blue focus ring.

## Layout & Spacing
- Use a Left Sidebar navigation (fixed width, white background, right border).
- Main Content area should have a maximum width or fluid layout with ample padding (32px).
- Generous gap between elements to avoid a cluttered look.
