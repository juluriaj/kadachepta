import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

// Web: served by the API itself, so same-origin requests carry the httpOnly session cookie.
// Native: bearer tokens (15-minute access + rotating refresh) kept in the OS keychain/keystore.
const IS_WEB = Platform.OS === 'web';
export const API_BASE = IS_WEB ? '' : (process.env.EXPO_PUBLIC_API_URL ?? 'http://10.0.2.2:8080');

const ACCESS = 'kc.access';
const REFRESH = 'kc.refresh';
const PROFILE = 'kc.profile';

let accessToken: string | null = null;
let refreshToken: string | null = null;
let profileId: string | null = null;
let parentPin: { pin: string; until: number } | null = null;
let refreshing: Promise<boolean> | null = null;
const signedOutListeners = new Set<() => void>();

export class ApiError extends Error {
  status: number;
  code?: string;
  body: Record<string, unknown>;
  diagnostics: string;
  constructor(status: number, body: Record<string, unknown>, method: string, path: string, requestId?: string | null) {
    super(String(body.error ?? body.detail ?? `Request failed (HTTP ${status})`));
    this.status = status;
    this.body = body;
    this.code = typeof body.code === 'string' ? body.code : undefined;
    this.diagnostics = `${method} ${path} → HTTP ${status}${requestId ? ` · request ${requestId}` : ''}`;
  }
}

export async function loadStoredSession() {
  profileId = await AsyncStorage.getItem(PROFILE);
  if (IS_WEB) return;
  accessToken = await SecureStore.getItemAsync(ACCESS);
  refreshToken = await SecureStore.getItemAsync(REFRESH);
}

export async function storeTokens(access: string | null, refresh: string | null) {
  accessToken = access;
  refreshToken = refresh;
  if (IS_WEB) return;
  if (access && refresh) {
    await SecureStore.setItemAsync(ACCESS, access);
    await SecureStore.setItemAsync(REFRESH, refresh);
  } else {
    await SecureStore.deleteItemAsync(ACCESS);
    await SecureStore.deleteItemAsync(REFRESH);
  }
}

export async function setProfileId(id: number | null) {
  profileId = id == null ? null : String(id);
  if (profileId) await AsyncStorage.setItem(PROFILE, profileId);
  else await AsyncStorage.removeItem(PROFILE);
}

export function getProfileId() {
  return profileId ? Number(profileId) : null;
}

// The parent PIN is remembered for five minutes after it's entered, then asked again.
export function rememberParentPin(pin: string) {
  parentPin = { pin, until: Date.now() + 5 * 60 * 1000 };
}
export function hasRecentParentPin() {
  return !!parentPin && parentPin.until > Date.now();
}
export function forgetParentPin() {
  parentPin = null;
}

export function onSignedOut(listener: () => void) {
  signedOutListeners.add(listener);
  return () => {
    signedOutListeners.delete(listener);
  };
}

export const clientKind = IS_WEB ? 'web' : 'mobile';

async function refreshAccess(): Promise<boolean> {
  if (!refreshToken) return false;
  refreshing ??= (async () => {
    try {
      const response = await fetch(`${API_BASE}/api/auth/refresh`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refreshToken }),
      });
      if (!response.ok) {
        await storeTokens(null, null);
        return false;
      }
      const body = await response.json();
      await storeTokens(body.accessToken, body.refreshToken);
      return true;
    } catch {
      return false; // offline: keep tokens and try again later
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

// For raw requests that can't go through api() (binary upload chunks).
export async function authHeaders(): Promise<Record<string, string>> {
  if (IS_WEB) return {};
  if (!accessToken) await refreshAccess();
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export async function refreshAfter401() {
  return !IS_WEB && refreshAccess();
}

type Options = { method?: string; body?: unknown; profile?: boolean; retry?: boolean };

export async function api<T = any>(path: string, { method = 'GET', body, profile = true, retry = true }: Options = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (!IS_WEB && accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (profile && profileId) headers['X-Profile-Id'] = profileId;
  if (parentPin && parentPin.until > Date.now()) headers['X-Parent-Pin'] = parentPin.pin;
  const response = await fetch(`${API_BASE}${path}`, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body),
    credentials: IS_WEB ? 'same-origin' : 'omit',
  });
  if (response.status === 401 && !IS_WEB && retry && (await refreshAccess())) {
    return api<T>(path, { method, body, profile, retry: false });
  }
  const text = await response.text();
  let data: any = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { error: text.slice(0, 200) };
  }
  if (!response.ok) {
    if (response.status === 401) signedOutListeners.forEach((listener) => listener());
    if (response.status === 404 && data.error?.includes?.('profile')) await setProfileId(null);
    throw new ApiError(response.status, data, method, path, response.headers.get('x-request-id'));
  }
  return data as T;
}

// Signed media paths come back relative on the API; native players need absolute URLs.
export function mediaUrl(path: string | null | undefined) {
  if (!path) return null;
  return path.startsWith('http') ? path : `${API_BASE}${path}`;
}
