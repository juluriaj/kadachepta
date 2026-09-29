# Phase 3 review: ratings, discovery, and community

Listeners rate what they actually listened to, families write reviews that are checked before anyone sees them,
narrators get public pages and can answer reviews, search understands Telugu typed in English letters, and Home
learns from listening ("Because you finished…") and from editors (collections).

## How to review

1. `npm start`, and start the GPU worker in your own terminal: `npm run worker:gpu` (LM Studio's server running,
   with `qwen/qwen3-8b` and `text-embedding-nomic-embed-text-v1.5` downloaded). The worker drafts conversation
   starters, checks reviews, and computes recommendations; without it those wait in the queue (46 jobs for the
   published stories are already queued).
2. **Listener:** phone (after the over-the-air update) or http://localhost:8080. Use a grown-up profile and a
   child profile in the same family.
3. **Editor:** http://localhost:8080/studio → the new Moderation, Starters, and Collections pages.

## Checklist

| # | Check | Where |
|---|---|---|
| 1 | After most of a story (60% heard, or the end), the player asks "How was the story?" and "How was the narration?" (stars). Not in bedtime mode: rate later on the story page | Player, story page |
| 2 | A child's profile gets four emoji reactions instead of stars; parents see "Children said 😍 2" | Player / story page on a child profile |
| 3 | Rating before listening says "Listen to most of the story first"; a parent can rate what their child listened to | Story page |
| 4 | Scores show only once there are enough ratings ("Not enough ratings yet"), as a Bayesian average weighted by how established each family is | Story page |
| 5 | A burst of ratings from new accounts is held out of the score and shown to editors: "Genuine: count them" / "Raid: leave them out" | Studio → Moderation |
| 6 | Grown-ups write a review; it says "Checking your review", then appears. Phone numbers, emails, links, or a child's school wait for an editor | Story page → What families say |
| 7 | Report a review (reason chips); two families reporting hides it until an editor decides | Story page, Studio → Moderation |
| 8 | Children's profiles never see reviews, follows, or updates | Child profile |
| 9 | Narrator pages: languages, followers, narration rating, stories, Follow | Story page → tap "Narrated by …" |
| 10 | Narrators see reviews of their stories and their narration rating, and can reply once per review (no contact details) | Studio tab → Reviews and ratings |
| 11 | Search: "kaaki", "kaki", "కాకి" and "crow" find the crow stories; "monkey" finds కోతి stories; typos forgiven | Home → search icon |
| 12 | "More like this" on the story page and "Because you finished …" on Home (after the worker computes recommendations and you finish a story) | Story page, Home |
| 13 | Conversation starters: after approval in the studio, parents see "Talk about it" questions on the story page | Studio → Starters; story page |
| 14 | Collections: create a festival or theme shelf with dates, order, and stories; it appears on Home in season, titled in the app language | Studio → Collections; Home |
| 15 | Updates (bell on Home, grown-ups only): turn on new stories from followed narrators and the next chapter of a series; nothing is sent until you turn them on; no streak nudges | Home → bell |
| 16 | Editors see each narrator's narration rating (the number payouts will weight by) | Studio → Narrators |
| 17 | Playlists per listener: create in Library → Playlists or from any story (“Add to playlist”, also in the player); tick to add or take out; Play all or Shuffle (the rest becomes the queue); reorder, rename, delete. A child's playlist only shows stories for their age | Library, story page, player |

## Decisions and limits worth knowing

- **Reviews are never auto-rejected.** In testing the local model got 5 of 7 sample reviews right: it let a child's
  name and school through and "blocked" a merely rude review. So it can only publish; anything it doubts goes to an
  editor, and a pattern check holds contact details and school names before the model sees them.
- **Conversation starters are English drafts.** The model's Telugu questions were ungrammatical ("కొవ్వెల" for crow),
  so editors write the Telugu ones; Telugu-UI parents see the English questions until then.
- **Recommendations** read each story's English teaser and details (nomic-embed-text), so they work for every story
  language, blended 70/30 with "families who finished this also finished". With 23 published stories and little
  listening yet, expect rough neighbours; they improve as the catalog and listening grow.
- **Search** runs in memory over the published catalog (milliseconds for thousands of stories) rather than in
  PostgreSQL full-text: one "loose Latin" form for Telugu script and English letters works better for mixed-script
  titles than language-specific full-text configurations. Revisit past ~20,000 stories.
- **Notifications are in-app only.** Phone push waits for the store builds (Phase 6).
