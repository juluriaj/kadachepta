import type { ConfigContext, ExpoConfig } from 'expo/config';

// Review builds talk to the desktop server over plain HTTP on the home network, which Android blocks
// by default. Only builds made with KC_ALLOW_HTTP=1 (the "preview" EAS profile) allow it; store builds
// use HTTPS and keep the default.
export default ({ config }: ConfigContext): ExpoConfig => ({
  ...(config as ExpoConfig),
  plugins: [
    ...(config.plugins ?? []),
    ['expo-build-properties', { android: { usesCleartextTraffic: process.env.KC_ALLOW_HTTP === '1' } }],
  ],
});
