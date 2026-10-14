import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Platform } from 'react-native';

import {
  api, clientKind, forgetParentPin, getProfileId, loadStoredSession, markSignedIn, onSignedOut, setProfileId, storeTokens,
} from './api';
import { useI18n, type UiLanguage } from './i18n';
import { getEngine } from './player/engine';

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
  changeLanguage: (language: UiLanguage) => Promise<void>;
};

const Context = createContext<SessionContext | null>(null);
// Editors and admins use the studio; narrators are listeners too (a household plus the Studio tab).
const STAFF_ROLES = new Set(['editor', 'admin']);

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { setLanguage } = useI18n();
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  // A language picked on the sign-in screen, saved to the account once it signs in.
  const pickedLanguage = useRef<UiLanguage | null>(null);

  useEffect(() => {
    loadStoredSession().finally(() => {
      setSelected(getProfileId());
      setLoaded(true);
    });
  }, []);

  // Startup waits on this one, so it gives up quickly: an unreachable server leads to the sign-in screen,
  // where review builds can change the server address, instead of an endless spinner.
  const sessionQuery = useQuery({
    queryKey: ['session'], enabled: loaded, staleTime: 60_000,
    queryFn: () => api<Session>('/api/session', { profile: false, timeoutMs: 8_000 }),
  });
  const session = useMemo<Session>(() => sessionQuery.data ?? { authenticated: false }, [sessionQuery.data]);
  useEffect(() => {
    if (session.authenticated) markSignedIn();  // a restored session re-arms the one-time sign-out notice
  }, [session.authenticated]);
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
      // State first: setProfileId makes the id visible to the start screen at once, and if the tabs saw it before this
      // state they would send everyone straight back there, round and round (a single-profile household on a new device).
      setSelected(id);
      await setProfileId(id);
      await queryClient.invalidateQueries({ predicate: (q) => !['session', 'household'].includes(String(q.queryKey[0])) });
    },
    signIn: async (body) => {
      const result = await api<Session & { accessToken?: string; refreshToken?: string }>(
        body.code ? '/api/auth/otp/verify' : '/api/login',
        { method: 'POST', body: { ...body, client: clientKind }, profile: false });
      if (result.accessToken && result.refreshToken) await storeTokens(result.accessToken, result.refreshToken);
      markSignedIn();
      const picked = pickedLanguage.current;
      if (picked && result.authenticated && !STAFF_ROLES.has(result.role ?? '') && picked !== result.uiLanguage) {
        try {  // before the session is cached, so the app doesn't flip back to the account's old language
          await api('/api/me/preferences', { method: 'PATCH', profile: false, body: { uiLanguage: picked } });
          result.uiLanguage = picked;
        } catch {
          // Signing in matters more: the language can be changed again from the home screen.
        }
      }
      pickedLanguage.current = null;
      queryClient.setQueryData(['session'], result);
      await queryClient.invalidateQueries({ queryKey: ['household'] });
      return result;
    },
    signOut: async () => {
      getEngine().stop();  // don't keep playing someone's story after they sign out
      try {
        await api('/api/logout', { method: 'POST', profile: false });
      } catch {
        // Offline or already signed out: signing out locally is what matters.
      } finally {
        await clearAll();
        if (Platform.OS === 'web') window.location.assign('/');
      }
    },
    refresh: async () => {
      await queryClient.invalidateQueries({ queryKey: ['session'] });
      await queryClient.invalidateQueries({ queryKey: ['household'] });
    },
    // Anyone can switch: it applies at once and is saved to the account (shared by the household's profiles).
    changeLanguage: async (language) => {
      setLanguage(language);
      if (!session.authenticated) {
        pickedLanguage.current = language;
        return;
      }
      if (isStaff) return;  // the studio is in English; staff accounts have no household preferences
      await api('/api/me/preferences', { method: 'PATCH', profile: false, body: { uiLanguage: language } });
      await queryClient.invalidateQueries({ queryKey: ['household'] });
    },
  }), [loaded, sessionQuery.isLoading, session, isStaff, householdQuery.data, householdQuery.isLoading, profile,
    queryClient, clearAll, setLanguage]);

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
