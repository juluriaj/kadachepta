import { ScrollView } from 'react-native';

import { AccountDetails } from '@/components/AccountDetails';
import { Text } from '@/components/ui';
import { useI18n } from '@/lib/i18n';
import { space } from '@/lib/theme';

export default function StudioProfile() {
  const { t } = useI18n();
  return (
    <ScrollView contentContainerStyle={{ padding: space.xl, gap: space.lg, maxWidth: 560, width: '100%', alignSelf: 'center' }}
      keyboardShouldPersistTaps="handled">
      <Text variant="title">{t('account.title')}</Text>
      <AccountDetails />
    </ScrollView>
  );
}
