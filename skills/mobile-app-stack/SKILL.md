---
name: mobile-app-stack
description: Recommends the default stack for a new Expo + React Native + TypeScript app (package manager, styling, animation, navigation, state, storage, dev workflow), one decision at a time. Use when the user starts a new mobile app, or asks which package manager, UI library, or dev workflow to use with Expo.
---

Default stance for a new Expo + TypeScript + React Native app. These are **recommendations with rationale**, not silent assumptions — walk through them one at a time using the same interview pattern as the `grilling` skill (state the recommendation and why, wait for confirmation, then move to the next), rather than applying them all at once. The user may deviate from any default; when they do, don't push back twice.

These defaults come from a real tech-stack interview for a content-heavy app with camera and audio recording. Update this file whenever a new project reveals a better default or a real exception to one of these.

## 1. Package manager → npm

**Default: npm.**

Why: it's Expo's own documented default (`create-expo-app`, all official docs and most community answers assume it) and has zero friction with EAS Build. pnpm and bun both still produce occasional native-module resolution quirks with Metro; yarn classic has known hoisting issues with RN native deps. Unless the user already has a strong pnpm/bun workflow they want to carry over, npm minimizes setup friction — which matters most early in a project, before there's a codebase to enforce conventions.

## 2. UI framework & animation approach → NativeWind + Reanimated (not Tamagui)

**Default: NativeWind (Tailwind CSS for React Native) for styling, React Native Reanimated for animation.** Avoid Tamagui unless the project has a specific reason to want its compiler/theme-token machinery.

Why NativeWind over Tamagui: Tamagui brings its own compiler step, which adds an ongoing Expo SDK compatibility risk, and its visual-identity advantage doesn't materialize for content/editorial-heavy apps (it shines more for utility-dense, many-small-interactive-component apps). Since code here is written largely by Claude Code (Sonnet/Opus), Tailwind's syntax is the most heavily represented styling system in LLM training data — it produces the most consistent, self-documenting output (`px-6 py-4 font-serif text-stone-800` reads like the diff itself), and its default spacing/typography scale prevents the drift you get from hand-rolled `StyleSheet` objects across many screens. NativeWind also has no extra compiler-compatibility risk beyond a standard Metro/Babel plugin.

Why Reanimated over any UI-library's built-in animation system (Tamagui's `animations-moti`/`animations-css`, Tailwind transitions, etc.): complex layout animations — a button expanding into a full screen, shape morphing, shared-element transitions — are not the strong point of any styling library's animation layer. Those libraries typically drop down to Reanimated under the hood anyway for this class of animation. Writing directly against Reanimated (plus `react-native-screens`' shared-element APIs where needed) keeps this decoupled from whatever styling system is in use.

If the project's visual identity is more "utility-dense SaaS/dashboard" than "editorial/content-forward," it's worth re-opening the Tamagui question rather than assuming NativeWind by default — the rationale above is specific to content-forward apps.

## 3. Dev/test workflow: hybrid web + real device

**Default: develop on Expo Web (`npx expo start --web`) for everything that isn't camera/mic-dependent; test native-sensitive screens on a real physical device.**

Why hybrid: Expo Web runs on `react-native-web`, so most of the app (navigation, layout, styling, business logic, content flows) iterates fast in a browser with no extra setup — no UI library is required for this. But native-sensitive APIs (`expo-camera`, `expo-audio`, etc.) have a narrower surface on web (permission flow doesn't reflect OS-level prompts, output file formats differ — native `.m4a` vs web `.webm`/`.ogg`), and **simulators/emulators have no real camera** — for a camera-dependent feature they are not a substitute for hardware.

### Expo Go vs development build — get the facts fresh, they move fast

This is the single most volatile area in this file. **Do not answer it from memory — check the Expo changelog and `expo.dev/go` at the time of asking.** The state as of August 2026, to show the *shape* of the tradeoff:

- Expo publishes a **separate Expo Go build per SDK**. On **Android** you can sideload any SDK's APK for free (`expo.dev/go?sdkVersion=<N>&platform=android&device=true`, the `expo-go-releases` GitHub releases, or Expo Orbit). So "latest SDK + Expo Go" is fully available on Android.
- On a **physical iOS device** you're limited to whatever the App Store build supports (pinned to SDK 54 as of May 2026), and current Expo docs state that installing Expo Go on an iOS device requires an **Apple Developer Program membership** via `npx eas-cli go` + TestFlight. Sources conflict on whether the free App Store route still works — have the user check the App Store directly, it takes two minutes.
- iOS **Simulator** can run other Expo Go versions for free, but see the no-real-camera caveat above.

How to steer the decision:
- **Start with Expo Go** unless the app needs a native module that isn't bundled in it. Zero build step, no EAS config, no paid account — that matters most early, when the app is small and iteration speed dominates.
- **Reach for a development build** when a required native module isn't in Expo Go (MMKV and most non-`expo-*` native libraries), or when approaching a store release.
- Choosing an older SDK to stay on the store Expo Go is a legitimate trade, but **state the debt out loud**: upgrading gets harder as the codebase grows, so it should be done deliberately at a known trigger (getting the Apple account, approaching release), not deferred indefinitely.
- Don't assume an older SDK forces outdated dependencies — **verify before claiming it.** (A concrete miss: Reanimated 4 was assumed to require the newest RN, but 4.0.x supports RN 0.78–0.81, so Expo SDK 54 runs it fine. The New Architecture has also been the default since SDK 53, so "old SDK = old architecture" is wrong too.)
- While on Expo Go, the whole stack must stay Expo Go-compatible. `expo-camera`, `expo-audio`, `expo-sqlite`, `expo-file-system` and Reanimated are bundled; NativeWind is build-time; Expo Router and Zustand are pure JS — so the defaults in this file are all compatible.

Always re-check the current Expo Go / SDK support state (Expo changelog) rather than trusting the numbers above; this is the fastest-moving fact in this file.

## 4. Navigation → Expo Router

**Default: Expo Router** (file-based routing). It's the `create-expo-app` default and the path Expo actively supports; file-based structure keeps screen organization tidy on its own. It also emits real URLs on web, which pairs well with the hybrid dev workflow above — you can jump straight to a screen in the browser instead of navigating there from scratch on every reload. React Navigation sits underneath it anyway; using it directly needs a specific reason.

## 5. State management → Zustand

**Default: Zustand.** Redux's boilerplate is disproportionate at typical app scale, and plain Context causes unnecessary re-renders and a sprawling provider tree as the app grows. Zustand sits between: minimal API, no provider required, good TypeScript inference.

## 6. Local persistence → match the shape of the data

Don't reach for a default here — pick from the data's shape:

- **Structured / historical / queryable data** (progress, streaks, session history, media metadata) → **`expo-sqlite`**. Queries like "which days did the user practice in the last 30" are naturally SQL. In a key-value store this collapses into one JSON blob rewritten on every update, which stops being queryable and starts being slow as it grows.
- **Simple scalar settings** (theme choice, volume) → AsyncStorage is fine; SQLite is overkill.
- **Media files** (audio/video recordings) → `expo-file-system` for the bytes, with only the *path* plus metadata in the database. When the user deletes a recording, delete the DB row and the file together in one place — split deletion leaves orphaned files that silently eat storage.

If the app will later sync to Postgres/Supabase, local SQLite keeps the data models consistent across both sides.

## 7. Recurring traps worth raising unprompted

These bite content-heavy or habit-tracking apps and are cheap to get right up front, expensive to retrofit:

- **Streak / "did I do it today" logic is timezone-sensitive.** Store practice days as a **local date string (`YYYY-MM-DD`)**, not a UTC timestamp — otherwise users practicing late in the evening get their streaks broken by the UTC/local midnight gap.
- **Turkish text** (or any locale with special casing): plain `toLowerCase()`/`toUpperCase()` corrupt the dotted/dotless **i/İ** distinction. Use `toLocaleLowerCase('tr')` / `toLocaleUpperCase('tr')`, and `localeCompare(..., 'tr')` for alphabetical sorting. Also verify **ğ, ş, ı, İ** glyphs render correctly in the chosen font — Google Fonts' `latin-ext` subset covers them, but rendering quality varies.
- **Font choice can be a functional constraint, not just aesthetic.** If text is meant to be read aloud, read at arm's length, or read by users with impaired vision, weight legibility over elegance — delicate old-style serifs (EB Garamond and similar) fade at distance where sturdier ones (Lora, Libre Baskerville) hold up.
- **Deferring dark mode is fine, but only if colors are design tokens from day one.** Raw hex values scattered through screens make retrofitting dark mode a full sweep of every file.
- **Store requirements for camera/mic apps**: permission description strings (`Info.plist` / Android manifest) and a privacy policy are mandatory for store review. Deferrable, but flag them so they don't surface as a launch-day surprise.

## 8. Where decisions get recorded

Record the outcome of this interview as a short decision log inside the target project (not in this skill) — e.g. `docs/decisions.md` or an ADR-style file — so the rationale survives independent of this skill and independent of chat history. Ask the user where they want it if the project doesn't already have a conventional location.
