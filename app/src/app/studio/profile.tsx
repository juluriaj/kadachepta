import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ScrollView } from 'react-native';

import { AccountDetails } from '@/components/AccountDetails';
import { Button, Card, Text } from '@/components/ui';
import { api, storeDeviceToken } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { space } from '@/lib/theme';

export default function StudioProfile() {
  const { t } = useI18n();
  return (
    <ScrollView contentContainerStyle={{ padding: space.xl, gap: space.lg, maxWidth: 560, width: '100%', alignSelf: 'center' }}
      keyboardShouldPersistTaps="handled">
      <Text variant="title">{t('account.title')}</Text>
      <AccountDetails />
      <RememberedDevices />
    </ScrollView>
  );
}

type Device = { id: number; createdAt: string; lastUsedAt: string | null; expiresAt: string; userAgent: string | null };

// Devices where "Remember this device" was ticked at the code step: they need only the password until they expire.
function RememberedDevices() {
  const query = useQuery({ queryKey: ['remembered-devices'],
    queryFn: () => api<{ days: number; devices: Device[] }>('/api/auth/devices', { profile: false }) });
  const [message, setMessage] = useState<string | null>(null);
  const devices = query.data?.devices ?? [];

  const forget = async () => {
    setMessage(null);
    try {
      const result = await api<{ forgotten: number }>('/api/auth/devices/forget', { method: 'POST', body: {}, profile: false });
      await storeDeviceToken(null);
      setMessage(`Forgot ${result.forgotten} device${result.forgotten === 1 ? '' : 's'}. Each one asks for the code at its next sign-in.`);
      await query.refetch();
    } catch (failure) {
      setMessage(failure instanceof Error ? failure.message : String(failure));
    }
  };

  return (
    <Card style={{ gap: space.sm }}>
      <Text variant="heading">Remembered devices</Text>
      <Text variant="small" muted>
        Devices where you ticked “Remember this device” skip the 6-digit code for {query.data?.days ?? 30} days. Forget
        them if you lose a device or signed in on someone else’s computer. Changing your password forgets them too.
      </Text>
      {!devices.length && query.data ? <Text variant="small">None right now.</Text> : null}
      {devices.map((device) => (
        <Text key={device.id} variant="small">
          {describe(device.userAgent)} · since {new Date(device.createdAt).toLocaleDateString()}
          {device.lastUsedAt ? ` · last used ${new Date(device.lastUsedAt).toLocaleDateString()}` : ''}
          {` · until ${new Date(device.expiresAt).toLocaleDateString()}`}
        </Text>
      ))}
      {devices.length ? <Button kind="secondary" title="Forget all devices" onPress={() => void forget()}
        style={{ alignSelf: 'flex-start' }} /> : null}
      {message ? <Text variant="small" muted>{message}</Text> : null}
    </Card>
  );
}

// "Chrome on Windows" from a user agent, good enough to tell devices apart.
function describe(userAgent: string | null) {
  if (!userAgent) return 'Unknown device';
  if (/okhttp|Expo|CFNetwork|Dalvik/i.test(userAgent)) return /iPhone|iPad|CFNetwork|Darwin/i.test(userAgent) ? 'iPhone app' : 'Android app';
  const browser = /Edg\//.test(userAgent) ? 'Edge' : /Firefox\//.test(userAgent) ? 'Firefox'
    : /Chrome\//.test(userAgent) ? 'Chrome' : /Safari\//.test(userAgent) ? 'Safari' : 'Browser';
  const system = /Windows/.test(userAgent) ? 'Windows' : /Android/.test(userAgent) ? 'Android'
    : /iPhone|iPad/.test(userAgent) ? 'iPhone' : /Mac OS X/.test(userAgent) ? 'Mac' : /Linux/.test(userAgent) ? 'Linux' : '';
  return system ? `${browser} on ${system}` : browser;
}
