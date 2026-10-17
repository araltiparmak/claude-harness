---
title: Web performance
markmap:
  colorFreezeLevel: 2
  initialExpandLevel: 2
  spacingVertical: 14
---

# Web performance

## Measure
- **Core Web Vitals**
  - LCP: largest paint
  - INP: input delay
  - CLS: layout shift
- Lab: [Lighthouse](https://developer.chrome.com/docs/lighthouse)
- Field: real-user monitoring

## Load less
- Code splitting
  - Route-level `import()`
- Images
  - `srcset` and AVIF
  - `loading="lazy"`
- Fonts
  - Subset, `font-display: swap`

## Load sooner
- CDN and caching
  - Hashed assets, `immutable`
- `preconnect` to key origins
- Server rendering

## Render faster
- Avoid long tasks
- Reserve space for media
- Virtualize long lists
