import { Redirect } from 'expo-router';
import { useEffect } from 'react';
import { Platform, View } from 'react-native';

import { Button, Loading, Screen, Text } from '@/components/ui';
import { useSession } from '@/lib/session';
import { space } from '@/lib/theme';

// Decides where a person lands: sign-in, onboarding, "who's listening?", or home.
export default function Gate() {
  const { ready, session, household, profile, isStaff, selectProfile, signOut } = useSession();
  const profiles = household?.profiles ?? [];
  const onlyProfile = profiles.length === 1 ? profiles[0] : null;

  useEffect(() => {
    if (onlyProfile && !profile) void selectProfile(onlyProfile.id);
  }, [onlyProfile, profile, selectProfile]);

  useEffect(() => {
    if (ready && isStaff && Platform.OS === 'web') {
      window.location.replace(session.role === 'narrator' ? '/narrator/' : '/editor/');
    }
  }, [ready, isStaff, session.role]);

  if (!ready) return <Loading />;
  if (!session.authenticated || session.mfaRequired || session.mfaEnrollmentRequired) return <Redirect href="/sign-in" />;
  if (isStaff) {
    if (Platform.OS === 'web') return <Loading />;
    return (
      <Screen>
        <View style={{ flex: 1, justifyContent: 'center', gap: space.lg }}>
          <Text variant="title">The studio is on the web</Text>
          <Text muted>Narrator and editor tools open in a browser at your KathaChepta address. This app is for listening.</Text>
          <Button title="Sign out" kind="secondary" onPress={signOut} />
        </View>
      </Screen>
    );
  }
  if (!household) return <Loading />;
  if (!household.household.onboarded) return <Redirect href="/onboarding" />;
  if (!profile) return onlyProfile ? <Loading /> : <Redirect href="/profiles" />;
  return <Redirect href="/(tabs)" />;
}
