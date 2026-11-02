// The privacy policy and terms of use shown at /privacy and /terms (English only for now).
// Keep them true to what the app does: change the text here when a feature changes what data is used or shared.

export type LegalSection = { heading: string; paragraphs: string[] };
export type LegalDocument = { title: string; updated: string; sections: LegalSection[] };

// An address for privacy questions. Empty: the pages point to "Send feedback" only.
export const CONTACT_EMAIL = '';

const contact = (): string =>
  'Use Send feedback in the app (Family tab, or the Narrate tab for narrators)'
  + (CONTACT_EMAIL ? `, or write to ${CONTACT_EMAIL}.` : '.');

export const PRIVACY: LegalDocument = {
  title: 'Privacy policy',
  updated: '2 November 2026',
  sections: [
    { heading: 'Who we are', paragraphs: [
      'KathaChepta is a story-listening app for families, at kathachepta.com. "We" means the KathaChepta team.',
    ] },
    { heading: 'What we collect', paragraphs: [
      'Your account: a username and password (the password is stored only as a one-way hash), and, if you add them, '
        + 'your name, email address, phone number and how you would like to be contacted.',
      'Your family: the profiles you create (a name, grown-up or child, an age band, an avatar and listening '
        + 'languages), your parental PIN (stored only as a hash) and the times of day you listen.',
      'Listening: what each profile played and how far, favorites, playlists, ratings, reviews (grown-ups only) and '
        + 'the narrators you follow. Downloaded stories stay on your device.',
      'Narrators: the recordings you submit, their transcripts, your narrator profile and editors\' notes on your '
        + 'submissions.',
      'Messages you send us with Send feedback.',
      'Technical details: your sign-in sessions, the IP address of sign-ins and security events, and whether you use '
        + 'the web, Android or iPhone app.',
      'Accounts from the old KathaChepta website: we moved your email address, username, display name, sign-up date '
        + 'and your password as the old site stored it (a one-way hash), so you can sign in with the same password. '
        + 'It is stored again with a stronger hash the first time you sign in.',
    ] },
    { heading: 'What we never do', paragraphs: [
      'We show no ads. We do not sell or rent personal data. We use no third-party analytics or advertising '
        + 'trackers, and we never track children for advertising. On the web, one cookie keeps you signed in.',
    ] },
    { heading: 'How we use it', paragraphs: [
      'To run the app: signing in, playing stories, family profiles, and suggestions based on what your family has '
        + 'listened to here. To publish narrators\' stories. To keep reviews safe (an automatic check, then our '
        + 'editors). To answer your feedback. To keep the service and your account secure.',
    ] },
    { heading: 'Children', paragraphs: [
      'Children do not have accounts. A parent or guardian creates children\'s profiles in their own account and is '
        + 'responsible for them. Children\'s profiles cannot write or see reviews, and settings sit behind the '
        + 'parental PIN. Suggestions for a child come only from what that profile listens to in KathaChepta.',
    ] },
    { heading: 'Who handles data for us', paragraphs: [
      'Amazon Web Services runs our servers and backups in Mumbai, India.',
      'Sarvam AI (India) turns narrators\' recordings into text and translates story text. Listeners\' details are '
        + 'not sent to Sarvam.',
      'Story summaries, titles and artwork are drafted by AI on our own computer, not by an outside AI service.',
      'We share personal data with no one else unless the law requires it.',
    ] },
    { heading: 'How long we keep it', paragraphs: [
      'As long as your account is open. When you delete your account (Family > Delete account), we remove your '
        + 'family\'s profiles and everything tied to them (listening history, favorites, playlists, ratings and '
        + 'reviews), your contact details, your password and your feedback messages. A record that the account '
        + 'existed, without personal details, stays for our security records. Backups are kept for up to 14 days, '
        + 'so deleted data leaves them within that time.',
    ] },
    { heading: 'Your choices', paragraphs: [
      'See and correct your details in Account. Download a copy of your data (Family > Download my data). Delete your '
        + 'account in the app at any time. Narrator and team accounts are closed by us on request.',
    ] },
    { heading: 'Security', paragraphs: [
      'Passwords and PINs are stored only as hashes, every connection is encrypted (HTTPS), and team accounts need '
        + 'two-step sign-in.',
    ] },
    { heading: 'Changes and contact', paragraphs: [
      'We will post changes on this page and tell you in the app when they matter.',
      `Questions or requests about your data: ${contact()}`,
    ] },
  ],
};

export const TERMS: LegalDocument = {
  title: 'Terms of use',
  updated: '2 November 2026',
  sections: [
    { heading: 'The service', paragraphs: [
      'KathaChepta lets families listen to stories and lets narrators submit recordings. It is free during the pilot. '
        + 'Features may change, and the service may sometimes be unavailable.',
    ] },
    { heading: 'Your account', paragraphs: [
      'You must be 18 or older to create an account. Children use KathaChepta only through a parent\'s or guardian\'s '
        + 'account. Give accurate details and keep your password to yourself: you are responsible for what happens in '
        + 'your account, including the profiles you create for children.',
    ] },
    { heading: 'Using KathaChepta fairly', paragraphs: [
      'Do not try to break into the service or other accounts, copy the catalog in bulk, or harass anyone. Reviews '
        + 'must not be abusive or spam, and must not share personal details such as a child\'s school. We may remove '
        + 'content and suspend accounts that break these rules.',
    ] },
    { heading: 'Stories and recordings', paragraphs: [
      'The stories, recordings and artwork in the app belong to KathaChepta or to the narrators who made them. You may '
        + 'listen to them for your own family\'s use, including downloads inside the app. Do not copy, publish or sell '
        + 'them.',
    ] },
    { heading: 'Narrators', paragraphs: [
      'When you submit a recording, you confirm that you have the right to it (the story and your performance), and '
        + 'you allow KathaChepta to edit and publish it in the app, together with its transcript, translations, '
        + 'titles, summaries and artwork made from it. Any payment is agreed separately.',
    ] },
    { heading: 'Reviews and ratings', paragraphs: [
      'You allow us to show your reviews and ratings in the app. We may check, hold or remove them.',
    ] },
    { heading: 'No guarantees', paragraphs: [
      'KathaChepta is provided as it is during the pilot. As far as the law allows, we are not responsible for '
        + 'interruptions or for indirect losses.',
    ] },
    { heading: 'Ending and changes', paragraphs: [
      'You can delete your account in the app at any time. We may close accounts that break these terms. We may '
        + 'update these terms; we will post the changes here and tell you in the app when they matter.',
      `Questions: ${contact()}`,
    ] },
  ],
};
