import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, View } from 'react-native';

import { Shelf } from '@/components/stories';
import { Avatar, Chip, ErrorState, Loading, Screen, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useSession } from '@/lib/session';
import { space } from '@/lib/theme';
import type { Shelf as ShelfType } from '@/lib/types';

const DURATIONS = [
  { id: 'any', max: Infinity },
  { id: '5', max: 5 * 60 },
  { id: '15', max: 15 * 60 },
  { id: '30', max: 30 * 60 },
];

function greetingKey(): TranslationKey {
  const hour = new Date().getHours();
  return hour < 12 ? 'home.greeting.morning' : hour < 17 ? 'home.greeting.afternoon' : 'home.greeting.evening';
}

export default function Home() {
  const { t } = useI18n();
  const colors = useColors();
  const { profile } = useSession();
  const [duration, setDuration] = useState('any');
  const [moment, setMoment] = useState<string | null>(null);
  const home = useQuery({
    queryKey: ['home', profile?.id], enabled: !!profile,
    queryFn: () => api<{ shelves: ShelfType[]; totalStories: number }>('/api/home'),
  });

  const shelves = useMemo(() => {
    const max = DURATIONS.find((d) => d.id === duration)?.max ?? Infinity;
    return (home.data?.shelves ?? [])
      .filter((shelf) => !moment || shelf.id === moment || shelf.id === 'continue')
      .map((shelf) => ({ ...shelf, items: shelf.items.filter((story) => (story.duration || 0) <= max) }))
      .filter((shelf) => shelf.items.length);
  }, [home.data, duration, moment]);

  const moments = (home.data?.shelves ?? []).filter((shelf) => shelf.moment).map((shelf) => shelf.moment!);

  if (!profile || home.isLoading) return <Loading />;
  return (
    <Screen padded={false}>
      <ScrollView contentContainerStyle={{ gap: space.xl, paddingBottom: space.xxl }}
        refreshControl={<RefreshControl refreshing={home.isRefetching} onRefresh={() => void home.refetch()} />}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, paddingHorizontal: space.lg, paddingTop: space.lg }}>
          <View style={{ flex: 1 }}>
            <Text variant="small" muted>{t('app.tagline')}</Text>
            <Text variant="title" accessibilityRole="header">{t(greetingKey(), { name: profile.name })}</Text>
          </View>
          <Pressable onPress={() => router.push('/profiles')} accessibilityRole="button" accessibilityLabel={t('profiles.who')}>
            <Avatar avatar={profile.avatar} size={44} />
          </Pressable>
        </View>

        {moments.length ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm, paddingHorizontal: space.lg }}>
            {moments.map((m) => (
              <Chip key={m} label={t(`moment.${m}` as TranslationKey)} selected={moment === m} onPress={() => setMoment(moment === m ? null : m)} />
            ))}
          </ScrollView>
        ) : null}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm, paddingHorizontal: space.lg }}>
          {DURATIONS.map((d) => (
            <Chip key={d.id} label={d.id === 'any' ? t('home.allDurations') : `≤ ${t('common.min', { n: d.id })}`}
              selected={duration === d.id} onPress={() => setDuration(d.id)}
              icon={d.id === 'any' ? undefined : <Ionicons name="time-outline" size={14} color={duration === d.id ? colors.onPrimary : colors.text} />} />
          ))}
        </ScrollView>

        {home.error ? <ErrorState error={home.error} onRetry={() => void home.refetch()} /> : null}
        {!home.error && !shelves.length ? (
          <View style={{ padding: space.xl, alignItems: 'center', gap: space.sm }}>
            <Ionicons name="book-outline" size={40} color={colors.muted} />
            <Text variant="heading">{t('home.empty')}</Text>
            <Text muted style={{ textAlign: 'center' }}>{t('home.emptyHint')}</Text>
          </View>
        ) : null}
        {shelves.map((shelf) => (
          <Shelf key={shelf.id} title={t(`shelf.${shelf.id}` as TranslationKey)} items={shelf.items} />
        ))}
      </ScrollView>
    </Screen>
  );
}
