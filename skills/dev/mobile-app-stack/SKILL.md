---
name: mobile-app-stack
description: Recommends the default stack for a new Expo + React Native + TypeScript app (package manager, styling, animation, navigation, state, storage, dev workflow), one decision at a time. Use when the user starts a new mobile app, or asks which package manager, UI library, or dev workflow to use with Expo.
---

Default stance for a new Expo + TypeScript + React Native app. These are **recommendations with rationale**: walk through them one at a time in the `grilling` interview pattern (state the recommendation and why, wait for confirmation, then move on). The user may deviate from any default; accept the first answer. Update this file when a project reveals a better default or a real exception.

## 1. Package manager → npm

It is Expo's documented default (`create-expo-app` and the official docs assume it) and has zero friction with EAS Build. pnpm and bun still produce occasional native-module resolution quirks with Metro; yarn classic has hoisting issues with RN native deps. Pick another only if the user has a strong workflow to carry over.

## 2. Styling and animation → NativeWind + Reanimated

- **NativeWind over Tamagui.** Tamagui's compiler adds an ongoing Expo SDK compatibility risk, and its strengths show in utility-dense, many-small-component apps rather than content-forward ones. Tailwind is the styling system best represented in LLM training data, so Claude's output stays consistent, and its spacing/type scale prevents drift across screens. For a dashboard-style app, re-open the Tamagui question.
- **Reanimated directly** for complex layout animation (expanding transitions, shape morphing, shared elements). Styling libraries drop down to Reanimated for this class anyway; writing against it keeps animation decoupled from styling.

## 3. Dev workflow → Expo Web + real device

Develop on Expo Web (`npx expo start --web`) for everything that is not camera/mic-dependent; test native-sensitive screens on a physical device. Native APIs (`expo-camera`, `expo-audio`) behave differently on web (permission flow, output formats: native `.m4a` vs web `.webm`), and **simulators have no real camera**.

### Expo Go vs development build

The most volatile fact in this file: **check the Expo changelog and `expo.dev/go` at the time of asking.** The state as of August 2026, to show the shape of the tradeoff:

- Expo publishes a separate Expo Go build per SDK. On **Android** any SDK's APK can be sideloaded for free (`expo.dev/go?sdkVersion=<N>&platform=android&device=true`, the `expo-go-releases` GitHub releases, or Expo Orbit).
- On a **physical iOS device** you get what the App Store build supports (SDK 54 as of May 2026); current docs say installing other versions needs an Apple Developer Program membership via `npx eas-cli go` + TestFlight. Sources conflict on the free App Store route, so have the user check the App Store.
- The iOS **Simulator** runs other Expo Go versions for free, but has no camera.

How to steer:
- **Start with Expo Go** unless the app needs a native module it doesn't bundle. No build step, no EAS config, no paid account.
- **Move to a development build** when a required native module is missing from Expo Go (MMKV and most non-`expo-*` native libraries), or when approaching a store release.
- Staying on an older SDK for the store Expo Go is a legitimate trade; **state the debt out loud** and name the trigger for upgrading (the Apple account, approaching release).
- **Verify before claiming an older SDK forces old dependencies.** (Reanimated 4.0.x supports RN 0.78–0.81, so SDK 54 runs it; the New Architecture is default since SDK 53.)
- The defaults in this file are all Expo Go-compatible: `expo-camera`, `expo-audio`, `expo-sqlite`, `expo-file-system` and Reanimated are bundled, NativeWind is build-time, Expo Router and Zustand are pure JS.

## 4. Navigation → Expo Router

The `create-expo-app` default and the path Expo supports. It emits real URLs on web, so with the web workflow you can jump straight to a screen on reload. Using React Navigation directly needs a specific reason.

## 5. State → Zustand

Redux's boilerplate is disproportionate at app scale, and plain Context causes re-renders and a sprawling provider tree. Zustand: minimal API, no provider, good TypeScript inference.

## 6. Local persistence → match the shape of the data

- **Structured, historical, queryable data** (progress, streaks, session history, media metadata) → `expo-sqlite`. In a key-value store it collapses into one JSON blob rewritten on every update.
- **Simple scalar settings** (theme, volume) → AsyncStorage.
- **Media files** → `expo-file-system` for the bytes, only the path plus metadata in the database. Delete the row and the file together in one place, or orphaned files eat storage.

Local SQLite also keeps data models consistent with a later Postgres/Supabase sync.

## 7. Traps to raise unprompted

- **Streak / "did I do it today" logic**: store days as a local date string (`YYYY-MM-DD`), not a UTC timestamp, or late-evening users lose streaks at the UTC/local midnight gap.
- **Locales with special casing** (dotted and dotless i): use `toLocaleLowerCase(locale)` / `toLocaleUpperCase(locale)` and `localeCompare(a, b, locale)`, and check the font renders the content's extended Latin glyphs (`latin-ext` subset).
- **Dark mode can wait if colors are design tokens from day one**; raw hex across screens makes the retrofit a full sweep.
- **Camera/mic apps**: permission description strings (`Info.plist` / Android manifest) and a privacy policy are mandatory for store review. Flag them early.

## 8. Record the decisions

Write the outcome as a short decision log in the target project (e.g. `docs/decisions.md` or an ADR), so the rationale outlives the chat. Ask where if the project has no convention.
