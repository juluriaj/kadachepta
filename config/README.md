# Local secrets

Copy `secrets.example.json` to `secrets.local.json` and replace the
placeholders with local development credentials.

`secrets.local.json` is ignored by Git and must never be committed, uploaded,
or shared. Prefer environment variables for CI and production:

```powershell
$env:SARVAM_API_KEY = "<rotated-key>"
```

The Sarvam key previously pasted into chat should be revoked and replaced
before use.
