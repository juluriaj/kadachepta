import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Platform } from 'react-native';

import {
  api, clientKind, forgetParentPin, getProfileId, loadStoredSession, onSignedOut, setProfileId, storeTokens,
} from './api';
import { useI18n, type UiLanguage } from './i18n';

export type Session = {
  authenticated: boolean;
  userId?: number;
  username?: string;
  email?: string | null;
  role?: string;
  permissions?: string[];
  uiLanguage?: UiLanguage;
  mfaRequired?: boolean;
  mfaEnrollmentRequired?: boolean;
};

export type Profile = {
  id: number;
  name: string;
  kind: 'adult' | 'child';
  ageBand: '3-5' | '6-8' | '9-12' | null;
  avatar: string;
  listeningLanguages: string[];
};

export type Household = {
  household: { id: number; name: string; moments: string[]; onboarded: boolean; hasParentPin: boolean };
  profiles: Profile[];
  account: { email: string | null; username: string | null; uiLanguage: UiLanguage; role: string };
  options: { ageBands: string[]; avatars: string[]; moments: string[]; listeningLanguages: string[] };
};

type SessionContext = {
  ready: boolean;
  session: Session;
  household: Household | undefined;
  profile: Profile | null;
  isStaff: boolean;
  isNarrator: boolean;
  selectProfile: (id: number | null) => Promise<void>;
  signIn: (body: Record<string, unknown>) => Promise<Session>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
};

const Context = createContext<SessionContext | null>(null);
// Editors and admins use the studio; narrators are listeners too (a household plus the Studio tab).
const STAFF_ROLES = new Set(['editor', 'admin']);

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { setLanguage } = useI18n();
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    loadStoredSession().finally(() => {
      setSelected(getProfileId());
      setLoaded(true);
    });
  }, []);

  const sessionQuery = useQuery({
    queryKey: ['session'], enabled: loaded, staleTime: 60_000,
    queryFn: () => api<Session>('/api/session', { profile: false }),
  });
  const session = useMemo<Session>(() => sessionQuery.data ?? { authenticated: false }, [sessionQuery.data]);
  const isStaff = STAFF_ROLES.has(session.role ?? '');
  const householdQuery = useQuery({
    queryKey: ['household'], enabled: session.authenticated && !isStaff,
    queryFn: () => api<Household>('/api/household', { profile: false }),
  });

  useEffect(() => {
    const language = householdQuery.data?.account.uiLanguage ?? session.uiLanguage;
    if (language === 'en' || language === 'te') setLanguage(language);
  }, [householdQuery.data?.account.uiLanguage, session.uiLanguage, setLanguage]);

  const clearAll = useCallback(async () => {
    await storeTokens(null, null);
    await setProfileId(null);
    forgetParentPin();
    setSelected(null);
    queryClient.clear();
    queryClient.setQueryData(['session'], { authenticated: false });
  }, [queryClient]);

  useEffect(() => onSignedOut(() => { void clearAll(); }), [clearAll]);

  const profile = useMemo(() => {
    const profiles = householdQuery.data?.profiles ?? [];
    return profiles.find((p) => p.id === selected) ?? null;
  }, [householdQuery.data, selected]);

  const value = useMemo<SessionContext>(() => ({
    ready: loaded && !sessionQuery.isLoading && (!session.authenticated || isStaff || !householdQuery.isLoading),
    session, household: householdQuery.data, profile, isStaff, isNarrator: session.role === 'narrator',
    selectProfile: async (id) => {
      await setProfileId(id);
      setSelected(id);
      await queryClient.invalidateQueries({ predicate: (q) => !['session', 'household'].includes(String(q.queryKey[0])) });
    },
    signIn: async (body) => {
      const result = await api<Session & { accessToken?: string; refreshToken?: string }>(
        body.code ? '/api/auth/otp/verify' : '/api/login',
        { method: 'POST', body: { ...body, client: clientKind }, profile: false });
      if (result.accessToken && result.refreshToken) await storeTokens(result.accessToken, result.refreshToken);
      queryClient.setQueryData(['session'], result);
      await queryClient.invalidateQueries({ queryKey: ['household'] });
      return result;
    },
    signOut: async () => {
      try {
        await api('/api/logout', { method: 'POST', profile: false });
      } finally {
        await clearAll();
        if (Platform.OS === 'web') window.location.assign('/');
      }
    },
    refresh: async () => {
      await queryClient.invalidateQueries({ queryKey: ['session'] });
      await queryClient.invalidateQueries({ queryKey: ['household'] });
    },
  }), [loaded, sessionQuery.isLoading, session, isStaff, householdQuery.data, householdQuery.isLoading, profile,
    queryClient, clearAll]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useSession() {
  const context = useContext(Context);
  if (!context) throw new Error('useSession must be used inside SessionProvider');
  return context;
}

// For route guards. Right after sign-in, a screen can render before the provider has re-rendered with
// the new session, and a guard reading the old "signed out" value sent staff straight back to sign-in.
// The query cache is already up to date at that point, so guards read it first.
export function useGuardSession() {
  const context = useSession();
  const cached = useQueryClient().getQueryData<Session>(['session']);
  const session = cached ?? context.session;
  return { ...context, session, isStaff: STAFF_ROLES.has(session.role ?? ''), isNarrator: session.role === 'narrator' };
}
