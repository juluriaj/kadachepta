import { Pressable } from 'react-native';

import { Text, useColors } from '@/components/ui';
import { useI18n } from '@/lib/i18n';
import { useSession } from '@/lib/session';
import { radius, space } from '@/lib/theme';

// One tap to the other app language, named in its own script so it can be found without reading this one.
export function LanguageSwitch() {
  const { t, language } = useI18n();
  const colors = useColors();
  const { changeLanguage } = useSession();
  const next = language === 'en' ? 'te' : 'en';
  const label = next === 'te' ? 'తెలుగు' : 'English';
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={`${t('common.changeLanguage')}: ${label}`} hitSlop={8}
      onPress={() => void changeLanguage(next).catch((error) => console.warn('Could not save the app language', error))}
      style={({ pressed }) => ({ paddingHorizontal: space.sm, paddingVertical: space.xs, borderRadius: radius.lg,
        borderWidth: 1, borderColor: colors.border, backgroundColor: pressed ? colors.surfaceAlt : 'transparent' })}>
      <Text variant="label" color={colors.primary}>{label}</Text>
    </Pressable>
  );
}
