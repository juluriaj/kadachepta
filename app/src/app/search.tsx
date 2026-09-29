import Ionicons from '@expo/vector-icons/Ionicons';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { FlatList, Pressable, TextInput, View } from 'react-native';

import { StoryRow } from '@/components/stories';
import { Screen, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { useSession } from '@/lib/session';
import { fontFor, radius, space, touch } from '@/lib/theme';
import type { Story } from '@/lib/types';

// Search in Telugu script or English letters (P3-05): "kaaki", "kaki", "కాకి", and "crow" all find the same story.
export default function Search() {
  const { t } = useI18n();
  const colors = useColors();
  const { profile } = useSession();
  const [text, setText] = useState('');
  const [query, setQuery] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => setQuery(text.trim()), 250);  // search as you type, without a request per key
    return () => clearTimeout(timer);
  }, [text]);
  const results = useQuery({
    queryKey: ['search', query, profile?.id], enabled: !!query, placeholderData: keepPreviousData,
    queryFn: () => api<{ items: Story[] }>(`/api/search?q=${encodeURIComponent(query)}`),
  });
  const items = query ? results.data?.items ?? [] : [];

  return (
    <Screen>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm, paddingVertical: space.md }}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} accessibilityRole="button"
          accessibilityLabel={t('common.back')} hitSlop={12}>
          <Ionicons name="chevron-back" size={26} color={colors.text} />
        </Pressable>
        <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: space.sm, minHeight: touch, borderRadius: radius.md,
          borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, paddingHorizontal: space.md }}>
          <Ionicons name="search" size={18} color={colors.muted} />
          <TextInput value={text} onChangeText={setText} placeholder={t('search.placeholder')} autoFocus autoCorrect={false}
            autoCapitalize="none" returnKeyType="search" accessibilityLabel={t('home.search')} placeholderTextColor={colors.muted}
            style={{ flex: 1, paddingVertical: space.sm, color: colors.text, fontSize: 16, fontFamily: fontFor(text) }} />
          {text ? (
            <Pressable onPress={() => setText('')} accessibilityRole="button" accessibilityLabel="Clear" hitSlop={8}>
              <Ionicons name="close-circle" size={18} color={colors.muted} />
            </Pressable>
          ) : null}
        </View>
      </View>
      <FlatList data={items} keyExtractor={(item) => item.id} keyboardShouldPersistTaps="handled"
        renderItem={({ item }) => <StoryRow story={item} />}
        ListEmptyComponent={
          <Text muted style={{ paddingVertical: space.lg }}>
            {!query ? t('search.hint') : results.error ? String(results.error) : results.isFetching ? ''
              : t('search.empty', { q: query })}
          </Text>} />
    </Screen>
  );
}
