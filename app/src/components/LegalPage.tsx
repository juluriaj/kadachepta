import { ScrollView, View } from 'react-native';

import { Screen, Text } from '@/components/ui';
import { useI18n } from '@/lib/i18n';
import type { LegalDocument } from '@/lib/legal';
import { space } from '@/lib/theme';

// The privacy policy or terms, readable signed out (they are linked from the sign-in screen).
export function LegalPage({ document }: { document: LegalDocument }) {
  const { t, language } = useI18n();
  return (
    <Screen back>
      <ScrollView contentContainerStyle={{ gap: space.lg, paddingVertical: space.lg, maxWidth: 720, width: '100%', alignSelf: 'center' }}>
        <Text variant="title" accessibilityRole="header">{document.title}</Text>
        <Text variant="small" muted>
          {t('legal.updated', { date: document.updated })}{language !== 'en' ? ` · ${t('legal.englishOnly')}` : ''}
        </Text>
        {document.sections.map((section) => (
          <View key={section.heading} style={{ gap: space.sm }}>
            <Text variant="heading" accessibilityRole="header">{section.heading}</Text>
            {section.paragraphs.map((paragraph) => <Text key={paragraph.slice(0, 40)}>{paragraph}</Text>)}
          </View>
        ))}
      </ScrollView>
    </Screen>
  );
}
