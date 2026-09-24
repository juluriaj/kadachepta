import { useQueryClient } from '@tanstack/react-query';
import { router, useFocusEffect } from 'expo-router';
import { useCallback, useEffect } from 'react';

import { Loading } from '@/components/ui';
import { getProfileId } from '@/lib/api';
import { useSession, type Household, type Session } from '@/lib/session';

type Target = '/sign-in' | '/studio' | '/onboarding' | '/profiles' | '/(tabs)' | null;

function decide(session: Session | undefined, household: Household | undefined, profileId: number | null): Target {
  if (!session) return null;
  if (!session.authenticated || session.mfaRequired || session.mfaEnrollmentRequired) return '/sign-in';
  if (['editor', 'admin'].includes(session.role ?? '')) return '/studio';
  if (!household) return null;
  if (!household.household.onboarded) return '/onboarding';
  const profiles = household.profiles;
  if (profiles.some((p) => p.id === profileId)) return '/(tabs)';
  return profiles.length === 1 ? null : '/profiles'; // one profile: selected automatically below
}

// Decides where a person lands: sign-in, the editor studio, onboarding, "who's listening?", or home.
// This screen stays underneath others in the stack, so each time it's shown it reads the *current* cache
// (not the values from its last render), which otherwise sent people back to onboarding after finishing it.
export default function Gate() {
  const queryClient = useQueryClient();
  const { ready, household, profile, selectProfile } = useSession();
  const onlyProfile = household?.profiles.length === 1 ? household.profiles[0] : null;

  const go = useCallback(() => {
    const target = decide(queryClient.getQueryData<Session>(['session']),
      queryClient.getQueryData<Household>(['household']), getProfileId());
    if (target) router.replace(target);
  }, [queryClient]);

  useEffect(() => {
    if (onlyProfile && !profile) void selectProfile(onlyProfile.id);
  }, [onlyProfile, profile, selectProfile]);

  useEffect(() => {
    if (ready) go();
  }, [ready, household, profile, go]);

  useFocusEffect(go);

  return <Loading />;
}
