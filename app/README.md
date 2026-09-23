# KathaChepta listener app

Expo (SDK 57) app for iOS, Android, and web. See the repository README for running it and
`docs/phase-1-review.md` for what it does. Agent notes: `AGENTS.md`.

| Command | What it does |
|---|---|
| `npx expo start` | Development server (Expo Go or a development build) |
| `npx expo export -p web` | Web build into `dist/`, served by the API at `/` |
| `npx eas-cli@latest build -p android --profile preview` | Installable Android review APK |
| `npx tsc --noEmit && npx expo lint` | Typecheck and lint |
| `node --test src/lib/player/logic.test.ts src/lib/i18n.test.ts` | Unit tests |
