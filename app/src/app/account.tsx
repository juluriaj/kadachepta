import { ScrollView } from 'react-native';

import { AccountDetails } from '@/components/AccountDetails';
import { Screen, Text } from '@/components/ui';
import { useI18n } from '@/lib/i18n';
import { space } from '@/lib/theme';

export default function Account() {
  const { t } = useI18n();
  return (
    <Screen back>
      <ScrollView contentContainerStyle={{ gap: space.lg, paddingVertical: space.lg }} keyboardShouldPersistTaps="handled">
        <Text variant="title" accessibilityRole="header">{t('account.title')}</Text>
        <AccountDetails />
      </ScrollView>
    </Screen>
  );
}
