# Phase 2 review: narrator studio and automated pipeline

A narrator records on a phone (or uploads a file), gets instant sound feedback, and sends the story in one
screen. Everything after that runs automatically (sound check → transcription → AI drafts and safety check →
artwork) until an editor reviews it on one screen and publishes with one action.

## How to review

1. `npm start`, and start the GPU worker: `npm run worker:gpu` (LM Studio's server must be running).
2. **Narrator (phone or browser):** sign in with any email (codes in Mailpit, http://localhost:8025),
   go to **Family → Become a narrator**, then the **Studio** tab → **New story**. Record in parts (pause,
   redo last part), or upload a file, fill in title and source, send.
3. **Editor:** sign in at http://localhost:8080 as an editor or admin → the studio opens (`/studio`).

## Checklist

| # | Check | Where |
|---|---|---|
| 1 | A listener becomes a narrator in one screen (agreement, languages, optional sample) | Family → Become a narrator |
| 2 | Record in the app: level meter with "too quiet/too loud", pause, redo last part, optional text to read from | Studio → New story |
| 3 | Or upload a file; big files upload in chunks and resume after a dropped connection | Studio → New story |
| 4 | Sound check result within a minute, with tips in Telugu or English | Submission page |
| 5 | Plain status timeline: Sound check → Transcription → Details and artwork → Editor review → Published | Submission page |
| 6 | Stories that fail the sound check stop before paid transcription; "Record again" keeps the details | Submission page |
| 7 | Studio queue: tabs (to review, needs attention, waiting on narrator, being prepared, catalog, published), waiting time and overdue marker, keyboard (j/k/x/Enter) | /studio |
| 8 | One review screen: audio + waveform + transcript (with confidence), editable teasers in Telugu and English, details with AI suggestions, safety flags, artwork, rights, checklist | Open any story |
| 9 | Publish in one action; nothing half-approved if something is missing | Review → Publish |
| 10 | Ask for changes with templated reasons; the narrator sees them translated and can resubmit | Review → Ask for changes |
| 11 | Trusted narrators: go first in the queue; bulk publish when every automatic check passes | Narrators, Queue |
| 12 | Catalog: "Prepare" makes free local drafts and artwork; paid transcription only by an admin, with the minutes shown | Queue → Catalog |
| 13 | AI & processing settings: model per task and language, artwork provider, prompt version, limits; "Test on one story"; worker status | /studio/settings (admin) |
| 14 | Series: chapters in order; the listener app's "Up next" follows the series | New story → Part of a series |

## What I tested

- **Automated:** 73 API tests (13 new for the pipeline, uploads, review, bulk publish, settings, and job
  batching; 5 for the safety word list, channel-name removal, and transcript confidence), 11 worker tests,
  10 app unit tests, typecheck and lint clean.
- **In the browser:** listener onboarding → became a narrator → uploaded a 76-second story → sound check,
  transcription (Sarvam), AI drafts, and local artwork ran automatically → the editor published it from the
  review screen. Studio queue, settings page (workers, LM Studio models), and narrators page.
- **Pilot catalog:** the 26 stories that already had transcripts were prepared with free local drafts and
  artwork, so the review queue has real stories.

## Being a critic: what isn't good enough yet

- **The local 8B model is weak at safety.** It rated every story "all-ages", including a ghost story and one
  where animals are killed. The word list and the rule "all-ages only when nothing is flagged" now catch
  these, but expect false alarms (for example a "knife" in a kitchen scene). Bulk publishing only applies to
  stories with no flags at all.
- **The 8 GB GPU can't hold the language model and the image model together.** With both loaded, an image
  took about 3 minutes. The worker now unloads one to run the other and takes jobs of the same kind in a row:
  about 12 seconds per image and 20 seconds per set of drafts, plus a 13-second model load at each switch.
- Genres and listening moments from the AI are rough ("Fable" and "bedtime" for a 41-minute novel chapter);
  editors should glance at them.
- **In-app recording and background upload are only verified in a desktop browser**, not on a phone
  (needs the Android build). Recording on web produces WebM; the server converts it.
- Push notifications are not in yet: narrators get in-app updates and email.
- The prototype editor and narrator pages still exist at `/editor/` and `/narrator/` as a fallback; they'll
  be removed after you sign off.
