# Phase 1 review: listener app

The new listener app (Expo: iOS, Android, and web from one codebase) replaces the prototype listener
page at http://localhost:8080. Staff and narrators who sign in on the web are sent to the editor and
narrator pages as before.

## How to review

**Web (phone or desktop browser):** `npm start`, then open http://localhost:8080. On a phone on the
same Wi-Fi: http://192.168.68.63:8080 (the desktop's current address; Windows may ask to allow
Docker through the firewall).

**Android app:** run `npx eas-cli login` once (free Expo account), then `npm run app:apk`. Expo builds
the APK in the cloud (about 15 minutes) and prints a link to install it on your phone. The build points
at `http://192.168.68.63:8080`; if the desktop's address changes, update `app/eas.json`.

**iPhone:** the browser version until the Apple developer account exists (Phase 6).

To start fresh as a new family: sign in with any email address. The 6-digit code appears in Mailpit at
http://localhost:8025 (no real email is sent locally).

## Checklist

| # | Check | Where |
|---|---|---|
| 1 | Sign in with an email code, no password | Sign-in screen |
| 2 | Onboarding: languages → children with age bands → listening moments | First sign-in |
| 3 | "Who's listening?" picker; a child profile sees only stories for their age and has no Family tab | Avatar on Home |
| 4 | Leaving a child profile asks for the parent PIN (after one is set) | Family → Set a parent PIN |
| 5 | Home is organized by moments (Bedtime, Drive, Run & walk, Work, Learn) with length filters | Home |
| 6 | Story page: teaser in your language, moral, resume position, favorite, download (Android) | Tap a story |
| 7 | Player: skip ±15/30 s, speeds 0.75–2×, sleep timer with a gentle fade, "stop at end of story" | Play a story |
| 8 | Bedtime mode: dark warm theme, 20-minute timer, never starts another story, "Goodnight" | Player → Bedtime mode |
| 9 | Drive mode: four huge buttons, screen stays on, series continue automatically | Player → car icon |
| 10 | Keeps playing with the screen locked, with lock-screen controls and artwork | Android app only |
| 11 | Offline: download, then play in airplane mode | Android app only |
| 12 | Family tab: minutes this week per child, screen-off share, streaks; add/remove children | Family |
| 13 | Telugu interface | Family → App language |
| 14 | Download my data; delete account | Family → Account |

## What I tested

- **Automated:** 55 API tests (profiles, child filtering, PIN, stats, export and deletion added this
  phase), 8 app unit tests (sleep fade, end-of-story rules, resume, listening-time counting, Telugu
  coverage), typecheck and lint clean.
- **In the browser at phone size:** onboarding with two children, home shelves, story page, playback,
  skip, speed, bedtime mode ending in "Goodnight" without starting another story, listening time
  recorded correctly (skipped audio isn't counted), child profile filtering, PIN on profile switch
  (wrong PIN rejected), Family stats, Telugu UI.

## Not verified yet, stated plainly

- **Background playback, lock-screen controls, and downloads are only testable on a phone build.**
  The code uses Expo's supported APIs for all three, but I haven't seen them run on a device.
- **Sign in with Apple and Google** need the store developer accounts and OAuth client IDs, so they
  move to Phase 6. Email codes work now.
- **Only one story is published**, so shelves repeat the same story. The 20 pilot transcripts are
  waiting for editor review; publishing them fills the app.
- Artwork is still from Pollinations and carries its watermark (replaced in Phase 2).
- Downloads don't expire yet; tying them to the subscription is Phase 4.
