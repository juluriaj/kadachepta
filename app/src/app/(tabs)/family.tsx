import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import { Platform, Pressable, ScrollView, Share, View } from 'react-native';

import { PinPad } from '@/components/ParentGate';
import { Avatar, Button, Card, Chip, ErrorState, Field, Loading, Screen, Text, useColors } from '@/components/ui';
import { api, ApiError, hasRecentParentPin, rememberParentPin } from '@/lib/api';
import { formatListening, useI18n, type TranslationKey } from '@/lib/i18n';
import { useSession, type Profile } from '@/lib/session';
import { radius, space } from '@/lib/theme';
import type { Stats } from '@/lib/types';

type FamilyStats = { profiles: (Profile & { stats: Stats })[] };

function today() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

export default function Family() {
  const { t, language, setLanguage } = useI18n();
  const colors = useColors();
  const queryClient = useQueryClient();
  const { household, signOut, refresh, isNarrator } = useSession();
  const hasPin = !!household?.household.hasParentPin;
  const [unlocked, setUnlocked] = useState(!hasPin || hasRecentParentPin());
  const [pinMode, setPinMode] = useState<'verify' | 'create' | null>(hasPin && !hasRecentParentPin() ? 'verify' : null);
  const [childName, setChildName] = useState('');
  const [childBand, setChildBand] = useState<'3-5' | '6-8' | '9-12'>('6-8');
  const [confirm, setConfirm] = useState('');
  const [message, setMessage] = useState<string | null>(null);

  const stats = useQuery({
    queryKey: ['family-stats'], enabled: unlocked,
    queryFn: () => api<FamilyStats>(`/api/household/stats?today=${today()}`, { profile: false }),
  });

  const act = async (work: () => Promise<unknown>, done?: string) => {
    setMessage(null);
    try {
      await work();
      if (done) setMessage(done);
      await refresh();
      await queryClient.invalidateQueries({ queryKey: ['family-stats'] });
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === 'parental-pin-required') {
        setUnlocked(false);
        setPinMode('verify');
      } else setMessage(failure instanceof Error ? failure.message : String(failure));
    }
  };

  if (!unlocked) {
    return (
      <Screen>
        <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: space.lg }}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.muted} />
          <Text variant="heading">{t('pin.enter')}</Text>
          <Button title={t('common.continue')} onPress={() => setPinMode('verify')} />
        </View>
        <PinPad visible={pinMode === 'verify'} onCancel={() => setPinMode(null)} onDone={() => { setPinMode(null); setUnlocked(true); }} />
      </Screen>
    );
  }
  if (!household) return <Loading />;

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ gap: space.xl, paddingVertical: space.lg }}>
        <Text variant="title" accessibilityRole="header">{t('family.title')}</Text>

        <Text variant="heading">{t('family.thisWeek')}</Text>
        {stats.isLoading ? <Loading /> : stats.error ? <ErrorState error={stats.error} onRetry={() => void stats.refetch()} /> : null}
        {(stats.data?.profiles ?? []).map((profile) => {
          const s = profile.stats;
          const top = Math.max(60, ...s.lastSevenDays.map((d) => d.seconds));
          return (
            <Card key={profile.id}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md }}>
                <Avatar avatar={profile.avatar} size={40} />
                <Text variant="heading" style={{ flex: 1 }}>{profile.name}</Text>
                <Text variant="heading" color={colors.primary}>{formatListening(t, s.weekSeconds)}</Text>
              </View>
              <View style={{ flexDirection: 'row', alignItems: 'flex-end', gap: 6, height: 56 }}
                accessibilityLabel={`Listening per day, last 7 days`}>
                {s.lastSevenDays.map((d) => (
                  <View key={d.day} style={{ flex: 1, height: Math.max(3, (d.seconds / top) * 56), borderRadius: 3,
                    backgroundColor: d.seconds ? colors.primary : colors.border }} />
                ))}
              </View>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.lg }}>
                <Metric label={t('family.screenOff')} value={s.weekScreenOffShare == null ? '–' : `${Math.round(s.weekScreenOffShare * 100)}%`} />
                <Metric label={t('family.finished')} value={String(s.storiesCompleted)} />
                <Metric label={t('family.streak')} value={String(s.streakDays)} />
              </View>
            </Card>
          );
        })}
        <Text variant="small" muted>{t('family.screenOffHint')}</Text>

        <Text variant="heading">{t('family.profiles')}</Text>
        {household.profiles.map((profile) => (
          <View key={profile.id} style={{ flexDirection: 'row', alignItems: 'center', gap: space.md }}>
            <Avatar avatar={profile.avatar} size={40} />
            <View style={{ flex: 1 }}>
              <Text variant="heading">{profile.name}</Text>
              <Text variant="small" muted>{profile.kind === 'child' && profile.ageBand ? t(`age.${profile.ageBand}`) : t('profiles.adult')}</Text>
            </View>
            {profile.kind === 'child' ? (
              <Pressable hitSlop={12} accessibilityRole="button" accessibilityLabel={`${t('library.remove')} ${profile.name}`}
                onPress={() => void act(() => api(`/api/household/profiles/${profile.id}`, { method: 'DELETE', profile: false }))}>
                <Ionicons name="trash-outline" size={20} color={colors.muted} />
              </Pressable>
            ) : null}
          </View>
        ))}
        <Card>
          <Field label={t('onboarding.kidName')} value={childName} onChangeText={setChildName} />
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
            {(['3-5', '6-8', '9-12'] as const).map((band) => (
              <Chip key={band} label={t(`age.${band}`)} selected={childBand === band} onPress={() => setChildBand(band)} />
            ))}
          </View>
          <Button title={t('profiles.add')} kind="secondary" disabled={!childName.trim()} onPress={() => void act(async () => {
            await api('/api/household/profiles', { method: 'POST', profile: false, body: { name: childName.trim(), kind: 'child', ageBand: childBand } });
            setChildName('');
          })} />
        </Card>

        <Text variant="heading">{t('family.pin')}</Text>
        <Text variant="small" muted>{t('family.pinHint')}</Text>
        <Button title={hasPin ? t('family.pinSet') : t('family.pinNew')} kind="secondary" onPress={() => setPinMode('create')} />

        <Text variant="heading">{t('family.language')}</Text>
        <View style={{ flexDirection: 'row', gap: space.sm }}>
          {(['en', 'te'] as const).map((code) => (
            <Chip key={code} label={code === 'en' ? 'English' : 'తెలుగు'} selected={language === code} onPress={() => void act(async () => {
              setLanguage(code);
              await api('/api/me/preferences', { method: 'PATCH', profile: false, body: { uiLanguage: code } });
            })} />
          ))}
        </View>

        <Text variant="heading">{t('family.moments')}</Text>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
          {household.options.moments.map((moment) => {
            const on = household.household.moments.includes(moment);
            return (
              <Chip key={moment} label={t(`moment.${moment}` as TranslationKey)} selected={on} onPress={() => void act(() => api('/api/me/preferences', {
                method: 'PATCH', profile: false,
                body: { moments: on ? household.household.moments.filter((m) => m !== moment) : [...household.household.moments, moment] },
              }))} />
            );
          })}
        </View>

        {!isNarrator ? (
          <Card>
            <Text variant="heading">{t('narrate.become')}</Text>
            <Text variant="small" muted>{t('narrate.becomeHint')}</Text>
            <Button kind="secondary" title={t('narrate.become')} onPress={() => router.push('/narrate/apply')}
              icon={<Ionicons name="mic-outline" size={18} color={colors.text} />} />
          </Card>
        ) : null}

        <Text variant="heading">{t('family.account')}</Text>
        <Text variant="small" muted>{household.account.email ?? household.account.username}</Text>
        <Button title={t('family.export')} kind="secondary" onPress={() => void act(async () => {
          const data = await api('/api/me/export', { profile: false });
          const json = JSON.stringify(data, null, 2);
          if (Platform.OS === 'web') {
            const link = document.createElement('a');
            link.href = URL.createObjectURL(new Blob([json], { type: 'application/json' }));
            link.download = 'kathachepta-data.json';
            link.click();
          } else await Share.share({ message: json, title: 'kathachepta-data.json' });
        })} />
        <Button title={t('family.signOut')} kind="secondary" onPress={signOut} />
        <Card style={{ borderColor: colors.danger }}>
          <Text variant="heading" color={colors.danger}>{t('family.delete')}</Text>
          <Text variant="small" muted>{t('family.deleteConfirm')}</Text>
          <Field label="DELETE" value={confirm} onChangeText={setConfirm} autoCapitalize="characters" />
          <Button title={t('family.delete')} kind="danger" disabled={confirm.trim().toUpperCase() !== 'DELETE'}
            onPress={() => void act(async () => {
              await api('/api/me/delete', { method: 'POST', profile: false, body: { confirm } });
              await signOut();
            })} />
        </Card>
        {message ? <Text color={colors.primary} accessibilityLiveRegion="polite">{message}</Text> : null}
      </ScrollView>
      <PinPad visible={pinMode === 'create'} mode="create" onCancel={() => setPinMode(null)} onDone={(pin) => {
        setPinMode(null);
        void act(async () => {
          await api('/api/household/pin', { method: 'POST', profile: false, body: { pin } });
          rememberParentPin(pin);
        }, t('common.done'));
      }} />
    </Screen>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  const colors = useColors();
  return (
    <View style={{ minWidth: 90, padding: space.sm, borderRadius: radius.md, backgroundColor: colors.surfaceAlt }}>
      <Text variant="heading">{value}</Text>
      <Text variant="small" muted>{label}</Text>
    </View>
  );
}
