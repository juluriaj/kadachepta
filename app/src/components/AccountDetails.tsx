import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { View } from 'react-native';

import { PinPad } from '@/components/ParentGate';
import { Button, Card, Chip, ErrorState, Field, Loading, Text, useColors } from '@/components/ui';
import { api, ApiError } from '@/lib/api';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { space } from '@/lib/theme';

export type ContactProfile = {
  userId: number; username: string | null; displayName: string | null; email: string | null; phone: string | null;
  contactChannel: 'email' | 'phone' | 'whatsapp'; contactNotes: string; role: string;
};

const CHANNELS = ['email', 'phone', 'whatsapp'] as const;

// Name, email, phone, and how to be contacted: the same form for listeners, parents, narrators, and staff.
export function AccountDetails() {
  const query = useQuery({ queryKey: ['my-profile'], queryFn: () => api<ContactProfile>('/api/me/profile', { profile: false }) });
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  return <DetailsForm key={query.data!.userId} profile={query.data!} />; // keep the form (and its messages) after saving
}

function DetailsForm({ profile }: { profile: ContactProfile }) {
  const { t } = useI18n();
  const colors = useColors();
  const queryClient = useQueryClient();
  const [name, setName] = useState(profile.displayName ?? '');
  const [phone, setPhone] = useState(profile.phone ?? '');
  const [channel, setChannel] = useState(profile.contactChannel);
  const [notes, setNotes] = useState(profile.contactNotes);
  const [newEmail, setNewEmail] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [codeSent, setCodeSent] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pinFor, setPinFor] = useState<(() => Promise<void>) | null>(null);

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await work();
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === 'parental-pin-required') setPinFor(() => work);
      else setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  const updated = async (result: ContactProfile) => {
    queryClient.setQueryData(['my-profile'], result);
    await queryClient.invalidateQueries({ queryKey: ['session'] });
  };

  const save = () => run(async () => {
    const result = await api<ContactProfile>('/api/me/profile', { method: 'PATCH', profile: false,
      body: { displayName: name.trim() || undefined, phone: phone.trim(), contactChannel: channel, contactNotes: notes } });
    await updated(result);
    setMessage(t('account.saved'));
  });

  const sendCode = () => run(async () => {
    await api('/api/me/email/request', { method: 'POST', profile: false, body: { email: newEmail?.trim() } });
    setCodeSent(true);
  });

  const confirmEmail = () => run(async () => {
    const result = await api<ContactProfile>('/api/me/email/confirm', { method: 'POST', profile: false,
      body: { email: newEmail?.trim(), code } });
    setNewEmail(null);
    setCodeSent(false);
    setCode('');
    await updated(result);
    setMessage(t('account.saved'));
  });

  return (
    <View style={{ gap: space.lg }}>
      <Text muted>{t('account.hint')}</Text>
      <Field label={t('account.name')} value={name} onChangeText={setName} autoComplete="name" />

      <Card>
        <Text variant="label" muted>{t('account.email')}</Text>
        <Text variant="heading">{profile.email ?? t('account.noEmail')}</Text>
        {newEmail === null ? (
          <Button kind="ghost" title={profile.email ? t('account.changeEmail') : t('account.addEmail')} onPress={() => setNewEmail('')} />
        ) : (
          <View style={{ gap: space.sm }}>
            <Field label={t('account.newEmail')} value={newEmail} onChangeText={setNewEmail} autoCapitalize="none"
              keyboardType="email-address" autoComplete="email" editable={!codeSent} />
            {codeSent ? (
              <>
                <Text variant="small" muted>{t('account.codeSent', { email: newEmail.trim() })}</Text>
                <Field label={t('signin.code')} value={code} onChangeText={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))}
                  keyboardType="number-pad" autoComplete="one-time-code" maxLength={6} />
                <Button title={t('account.confirm')} disabled={code.length !== 6} loading={busy} onPress={() => void confirmEmail()} />
              </>
            ) : (
              <Button title={t('signin.sendCode')} disabled={!newEmail.includes('@')} loading={busy} onPress={() => void sendCode()} />
            )}
            <Button kind="ghost" title={t('common.cancel')} onPress={() => { setNewEmail(null); setCodeSent(false); setCode(''); }} />
          </View>
        )}
      </Card>

      <Field label={t('account.phone')} value={phone} onChangeText={setPhone} keyboardType="phone-pad" autoComplete="tel"
        placeholder="+91 98765 43210" />
      <Text variant="label" muted>{t('account.channel')}</Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
        {CHANNELS.map((option) => (
          <Chip key={option} label={t(`contact.${option}` as TranslationKey)} selected={channel === option}
            onPress={() => setChannel(option)} />
        ))}
      </View>
      <Field label={t('account.notes')} value={notes} onChangeText={setNotes} maxLength={300} />

      {error ? <Text color={colors.danger} accessibilityLiveRegion="polite">{error}</Text> : null}
      {message ? <Text color={colors.success} accessibilityLiveRegion="polite">{message}</Text> : null}
      <Button title={t('common.save')} loading={busy && newEmail === null} onPress={() => void save()} />

      <PinPad visible={!!pinFor} onCancel={() => setPinFor(null)} onDone={() => {
        const retry = pinFor;
        setPinFor(null);
        if (retry) void run(retry);
      }} />
    </View>
  );
}
