# Content policy and age rubric

KathaChepta is for families, including children aged 3 and up. This policy is what editors apply when they
review a story and what the AI safety pre-check is asked to look for. The machine-readable version lives in
`api/app/services/policy.py` and must stay in step with this page.

## What we publish

- Human narration only. AI-generated voices are never presented as a person's narration.
- Stories the narrator may narrate: their own work, public-domain and traditional tales, KathaChepta-owned
  stories, or work licensed to them (with evidence).
- No added music or sound effects the narrator doesn't have rights to.
- No advertising, sponsorship reads, or links to other services inside recordings. The spoken channel name
  at the start and end of catalog recordings is allowed; it's removed from transcripts automatically.

## Age rubric

A story's age range is its **youngest suitable age**, not its target audience. Child profiles only see
stories whose range starts at or below their age band, and under-9s never see stories with content warnings.

| Band | What it allows |
|---|---|
| 3–5 | Gentle stories. Mild peril resolved quickly; no deaths on-screen; no scary villains. |
| 6–8 | Clear right and wrong; mild peril and cartoon conflict; deaths only off-screen and not dwelt on (as in fables). |
| 9–12 | Adventure, battles described without gore, loss and grief handled with care, mythological conflict. |
| 13+ | Historical fiction and epics with war, cruelty, or mature themes; no explicit content. |

## Content flags

Editors (and the AI pre-check) flag these so parents know what's in a story:

| Flag | Examples |
|---|---|
| fear | Ghosts, demons, monsters, threats |
| violence | Fighting, injury, weapons, cruelty (including to animals) |
| death | Death or killing of people or animals |
| loss | Grief, abandonment, separation from family |
| romance | Relationships beyond a child's understanding |
| discrimination | Stereotypes or demeaning language about caste, religion, gender, region, or disability |
| imitation | Dangerous behaviour a child might copy (fire, poison, running away, talking to strangers) |
| language | Rude words or insults |

Flags inform; they don't forbid. A fable where a wolf is punished is fine for 6+ with a "violence" flag.

## How safety is checked

1. **AI pre-check** (local model): lists flags with evidence and suggests a rating.
2. **Word list** (per language): catches words for death, killing, ghosts, blood, and war that small local
   models miss. It is deliberately over-inclusive: a hit only sends the story to a person.
3. **Derived rating**: "all-ages" only when neither found anything. The model can make a rating stricter,
   never looser.
4. **Editor decision**: the editor confirms the age range against this rubric before publishing
   (review checklist). Bulk publishing is only offered for stories rated all-ages with nothing flagged.

## Review checklist (before publishing)

- I listened to the start, a middle section, and the end.
- The age range matches the rubric, including the AI safety flags.
- It's a human narration (no AI voice presented as human).
- The teaser has no spoilers and no invented facts.
- Optional: the artwork suits the story and has no text or watermark.

## Asking narrators for changes

Editors choose one or more templated reasons (translated for the narrator) and can add a note with
timestamps: background noise, uneven volume, mistakes left in, incomplete story, content not suitable for the
audience, rights details needed, title or details wrong, language mismatch, or other.
