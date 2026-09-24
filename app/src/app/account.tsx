import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { Pressable, ScrollView } from 'react-native';

import { AccountDetails } from '@/components/AccountDetails';
import { Screen, Text, useColors } from '@/components/ui';
import { useI18n } from '@/lib/i18n';
import { space } from '@/lib/theme';

export default function Account() {
  const { t } = useI18n();
  const colors = useColors();
  return (
    <Screen>
      <ScrollView contentContainerStyle={{ gap: space.lg, paddingVertical: space.lg }} keyboardShouldPersistTaps="handled">
        <Pressable accessibilityRole="button" accessibilityLabel={t('common.back')} hitSlop={12}
          onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))}>
          <Ionicons name="chevron-back" size={26} color={colors.text} />
        </Pressable>
        <Text variant="title" accessibilityRole="header">{t('account.title')}</Text>
        <AccountDetails />
      </ScrollView>
    </Screen>
  );
}
