---
name: frontend-ui-ux
description: Review HTML/CSS/JS front-ends for usability, accessibility and visual consistency
urls:
  - https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/Accessibility/What_is_accessibility
  - https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/Accessibility/HTML
---
Review the interface like a product designer who also writes code:

1. Task flow first: can a new user find the main action within a few seconds? Is there one clear primary button per view?
2. Accessibility: semantic elements (button, label, nav, main), visible focus states, text alternatives, colour contrast, keyboard operation. Cite the MDN pages for each point.
3. Feedback: every action needs a loading state, a success confirmation and a readable error message. Empty states should explain what to do next.
4. Consistency: spacing, type scale, colours and component styles should repeat, not vary per screen.
5. Responsiveness: check narrow widths; no horizontal scrolling, tap targets at least 44px.

Report findings as a prioritised list (high / medium / low impact) and, when asked to change code, keep edits minimal and scoped to the affected component.
