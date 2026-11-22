# Soft launch: existing users first, then social posts

The app is live at `https://app.kathachepta.com` (Lightsail, since 2026-11-02). The soft launch opens it in
three waves, each one starting when the one before is calm: few complaints, no outages, feedback answered.

| Wave | Who | How | When |
|---|---|---|---|
| 0. Friends and family | 10–20 people you know, 2–3 of them narrators | WhatsApp, personally | Week 1 |
| 1. Existing users | The 1203 accounts imported from the old site, newest sign-ups first | Email from your Zoho mailbox, in daily batches | Weeks 2–3 |
| 2. Social posts | New families, and new narrators | Facebook groups, Instagram, WhatsApp communities | Week 4 onwards |

**What success looks like after 4 weeks:** about 150 families who listened more than once, 20 narrator
applications, 10 new stories published from new narrators, no day with the site down, and every piece of
feedback answered within two days.

## Before the first invite (checklist)

- [ ] **Smoke test:**
  - Studio sign-in with two-factor.
  - A narrator submission all the way to published, including the evening teaser and artwork.
  - One old-site account signing in with its old password.
- [ ] **Catalog:** publish the 56 Barister Parvateesam chapters waiting for review, and give the book a cover
      (Studio › Books). Check that Home shows full shelves for Telugu.
- [ ] **Legal:** fill `CONTACT_EMAIL` in `app/src/lib/legal.ts`, then read the privacy policy and terms once
      more, ideally with a lawyer. Deploy.
- [ ] **Alerts:** add an email address for the Lightsail "server down" alarm, so you hear about an outage
      before your users do.
- [ ] **Forgotten passwords** (see the next section): decide how you'll handle them.
- [ ] **Capacity:** the $7 plan has about 300 MB of memory to spare. Wave 1 is fine on it. Move to the $24
      plan before wave 2 (runbook: "Moving to a bigger plan", about 30 minutes of downtime).

### Forgotten passwords

Most imported accounts signed up in 2018–2020, so many people won't remember their old password, and email is
off, so they can't reset it themselves. Three ways to handle it:

1. **Tell them to create a new account** (recommended for the pilot). Imported accounts have no listening
   history in the app, so nothing is lost. The invite says so, and nobody has to wait for you.
2. **Reset by hand:** Studio › Users › Reset password, then send them the new password. That's fine for a
   handful of people, but slow for hundreds.
3. **Turn on email** before wave 1, so people reset their own (backlog P6-10). That needs an SMTP provider.
   Zoho's free plan may not allow it; SES needs production access.

## Wave 0: friends and family (week 1)

- Send the link on WhatsApp to people who will tell you the truth. Ask 2–3 of them to become narrators and
  record one story each, so the narrator path is tried by real people before strangers use it.
- Ask everyone for one thing: "Use it at bedtime twice this week and send feedback from the Family tab."
- Each evening, read Studio › Feedback and fix what breaks. Start wave 1 when a few days go by with no new bugs.

## Wave 1: the old site's users (weeks 2–3)

**The list.** The accounts are on the server; the email addresses never go through chat. I can export them
to a CSV on the server, split by sign-up year, for you to copy to your PC.

**Order:** newest sign-ups first, since they're the most likely to still read that inbox and remember the
site:

| Batch | Signed up | Accounts |
|---|---|---|
| 1 | 2021–2026 | 184 |
| 2 | 2020 | 282 |
| 3 | 2019 | 414 |
| 4 | 2017–2018 | 324 |

**Sending:**
- Send from a real person's address on kadachepta.com (Zoho), as plain text, one email per person (a mail merge
  or Zoho's own campaign tool). Don't put hundreds of people in BCC on one email: it lands in spam.
- Check Zoho's daily sending limit for your plan and stay under it. About 100 a day is a safe pace, and it also
  spreads the first sign-ins over the week.
- Everyone gets one email. No reminders to people who don't open it.
- Each day, watch three things: new sign-ins, the feedback inbox, and server memory (`npm run server -- status`).

**Invite email (English):**

> Subject: KathaChepta is back: Telugu stories for your family
>
> Hello,
>
> You signed up on the KathaChepta website a while ago. We've rebuilt it as an app for families: hundreds of
> Telugu stories for bedtime, car rides and quiet afternoons, with grown-up and child profiles, and stories that
> keep your place.
>
> Try it at https://app.kathachepta.com
>
> Sign in with your old username or email and your old password. If you don't remember the password, just tap
> "Create an account". It takes a minute, and you lose nothing.
>
> It's free while we're in our pilot. We'd love to hear what you think: there's a "Send feedback" button in the
> Family tab.
>
> If you'd rather not hear from us again, reply and say so. You can also delete your account from the app.
>
> [Your name]
> KathaChepta

**Invite email (Telugu):**

> విషయం: KathaChepta మళ్ళీ వచ్చింది: మీ కుటుంబం కోసం తెలుగు కథలు
>
> నమస్కారం,
>
> మీరు కొంతకాలం క్రితం KathaChepta వెబ్‌సైట్‌లో చేరారు. ఇప్పుడు దాన్ని కుటుంబాల కోసం యాప్‌గా మళ్ళీ తయారు
> చేశాము: నిద్రపోయే ముందు, ప్రయాణాల్లో వినడానికి వందలాది తెలుగు కథలు, పెద్దలకు, పిల్లలకు వేర్వేరు ప్రొఫైల్‌లు,
> ఆపిన చోటు నుండే మళ్ళీ మొదలయ్యే కథలు.
>
> ఇక్కడ ప్రయత్నించండి: https://app.kathachepta.com
>
> మీ పాత యూజర్‌నేమ్ లేదా ఈమెయిల్, పాత పాస్‌వర్డ్‌తో సైన్ ఇన్ చేయండి. పాస్‌వర్డ్ గుర్తులేకపోతే "ఖాతా తెరవండి"
> నొక్కండి. ఒక్క నిమిషం పడుతుంది, మీరు ఏమీ కోల్పోరు.
>
> పైలట్ సమయంలో ఇది ఉచితం. మీ అభిప్రాయం తెలుసుకోవాలని ఉంది: ఫ్యామిలీ ట్యాబ్‌లో "అభిప్రాయం పంపండి" బటన్ ఉంది.
>
> మా నుండి ఇకపై సందేశాలు వద్దనుకుంటే, ఈ ఈమెయిల్‌కు జవాబిచ్చి చెప్పండి. యాప్ నుండి మీ ఖాతాను తొలగించవచ్చు కూడా.
>
> [మీ పేరు]
> KathaChepta

## Wave 2: social posts (week 4 onwards)

Two audiences with different messages. Post them on different days, so you can tell which one brings people.

**Where:** Telugu parents' Facebook groups (ask the admins first), Telugu NRI community groups (US, UK, Gulf),
Instagram (a 30-second clip of a story with its artwork), WhatsApp communities and status, and schools or
libraries you know.

**Families:**

> Looking for Telugu stories your kids will actually ask for at bedtime? KathaChepta has hundreds of them,
> narrated by real people, free during our pilot. Grown-up and child profiles, no ads.
> https://kathachepta.com

**Narrators:**

> Do you love telling stories in Telugu? Become a KathaChepta narrator. Record on your phone, and our editors
> help polish it. Your story reaches families here and abroad, with your name, photo and page, ratings, and
> thank-you notes from listeners. Apply in the app: Family tab › Become a narrator.
> https://kathachepta.com

**Narrator capacity.** Every submission needs your review, and teasers and artwork are made only in the
evening. Paid transcription (Sarvam) is also charged per minute. Take about 10 new narrators a week:
- Approve the ones whose sample sounds good.
- Keep a WhatsApp group for narrators, to answer questions in one place.
- Mark them trusted once they have a clean record (Studio › Narrators).

## Should you mention that payments are coming?

**For families: no.** "It will be paid later" is a reason to wait, not a reason to join. Say "free during our
pilot", which is what the terms already say, and don't promise free forever. If someone asks, the honest answer
is: "Paid plans will come later; families who join in the pilot will hear first." Offer a founding-family
discount only once you've decided pricing (backlog D6).

**For narrators: yes, carefully.** Earning from narration is a real reason to join, but only make a promise you
can keep:

- **Say:** "We plan to share revenue with narrators once paid plans launch."
- **Optional promise:** "Stories you publish in the pilot will count." Only add this if you're willing to pay
  for pilot work later. The earnings model in the backlog (P5) can count published minutes and ratings from
  any date.
- **Don't say:** amounts, per-minute rates or dates. Phase 5 isn't built and the rates aren't decided, and a
  number you can't keep loses the narrators you most want. Advertising standards in India (ASCI) also expect
  earning claims to be specific and true.
- **Lead with what works today:** families hear their voice, and they get a page with their photo,
  followers, ratings and thank-you notes.
- **Paperwork first:** before money changes hands, the narrator agreement needs payment terms, and India
  requires TDS on payouts (P5-06).

## Week by week

| Week | Do | Watch |
|---|---|---|
| 1 | Checklist, wave 0 (friends and family, 2–3 narrators) | Feedback each evening; every bug fixed |
| 2 | Wave 1, batches 1–2 (2020 onwards) | Sign-ins a day, password questions, server memory |
| 3 | Wave 1, batches 3–4; move to the $24 plan | The same, plus narrator applications |
| 4 | Wave 2: the families post, then the narrators post a few days later | Which post brings sign-ups; the review queue's length |
| 5+ | Android APK for pilot families (runbook stage 2) | Playback and downloads on phones |

## Risks and what to do

| Risk | What to do |
|---|---|
| Many forgotten passwords | The invite points to "Create an account". Reset by hand only for people who ask |
| Emails land in spam | Plain text from a real person, one per person, small daily batches |
| The server slows down | `npm run server -- status` each day; the $24 plan before wave 2 |
| Spam sign-ups | Sign-up is rate-limited per address. Watch for bursts of new accounts and close sign-up if needed |
| Reviews and notes wait until evening | Expected (the GPU check runs 7 pm–6 am). Say "checked within a day" if anyone asks |
| More narrators than you can review | Approve applications in batches; a waiting list is fine |
| A child-safety problem in a review or note | It's held for you in Studio › Moderation. Check it every evening during the launch |
