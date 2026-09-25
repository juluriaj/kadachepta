import Ionicons from '@expo/vector-icons/Ionicons';
import { View } from 'react-native';

import { Chip, Text, useColors } from '@/components/ui';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { space } from '@/lib/theme';
import type { QcCheck, SubmissionDetail } from '@/lib/types';

export const SOURCE_TYPES = ['original', 'public-domain', 'kathachepta-owned', 'licensed'] as const;
export type SourceType = (typeof SOURCE_TYPES)[number];

const TONE: Record<string, 'good' | 'wait' | 'act' | 'bad'> = {
  published: 'good', ready: 'wait', checking: 'wait', transcribing: 'wait', drafting: 'wait', illustrating: 'wait',
  'waiting-transcript': 'wait', 'awaiting-submit': 'act', 'needs-fix': 'act', 'changes-requested': 'act',
  rejected: 'bad', failed: 'bad', none: 'wait',
};

export function StageBadge({ stage }: { stage: string }) {
  const { t } = useI18n();
  const colors = useColors();
  const tone = TONE[stage] ?? 'wait';
  const color = { good: colors.success, wait: colors.muted, act: colors.accent, bad: colors.danger }[tone];
  const icon = { good: 'checkmark-circle', wait: 'time-outline', act: 'alert-circle', bad: 'close-circle' }[tone] as
    keyof typeof Ionicons.glyphMap;
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
      <Ionicons name={icon} size={14} color={color} />
      <Text variant="label" color={color}>{t(`stage.${stage}` as TranslationKey)}</Text>
    </View>
  );
}

export function Timeline({ steps }: { steps: SubmissionDetail['timeline'] }) {
  const { t } = useI18n();
  const colors = useColors();
  return (
    <View style={{ gap: space.sm }} accessibilityRole="list">
      {steps.map((step) => {
        const color = { done: colors.success, current: colors.primary, todo: colors.border, blocked: colors.accent }[step.state];
        const icon = { done: 'checkmark-circle', current: 'ellipse', todo: 'ellipse-outline', blocked: 'alert-circle' }[step.state] as
          keyof typeof Ionicons.glyphMap;
        return (
          <View key={step.key} style={{ flexDirection: 'row', alignItems: 'center', gap: space.md }}>
            <Ionicons name={icon} size={22} color={color} />
            <Text variant={step.state === 'current' || step.state === 'blocked' ? 'heading' : 'body'}
              muted={step.state === 'todo'}>{t(`step.${step.key}` as TranslationKey)}</Text>
          </View>
        );
      })}
    </View>
  );
}

// QC tips are translated by check code; the server's English text is the fallback.
export function QcList({ checks }: { checks: QcCheck[] }) {
  const { t, language } = useI18n();
  const colors = useColors();
  return (
    <View style={{ gap: space.md }}>
      {checks.map((check) => {
        const key = `qc.${check.code}` as TranslationKey;
        const tip = language === 'en' ? check.tip : t(key) !== key ? t(key) : check.tip;
        return (
          <View key={check.code} style={{ flexDirection: 'row', gap: space.sm }}>
            <Ionicons name={check.level === 'fail' ? 'close-circle' : 'warning'} size={20}
              color={check.level === 'fail' ? colors.danger : colors.accent} />
            <View style={{ flex: 1, gap: 2 }}>
              <Text>{check.message}</Text>
              {tip ? <Text variant="small" muted>{tip}</Text> : null}
            </View>
          </View>
        );
      })}
    </View>
  );
}

export function SourcePicker({ value, onChange }: { value: SourceType | null; onChange: (value: SourceType) => void }) {
  const { t } = useI18n();
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
      {SOURCE_TYPES.map((type) => (
        <Chip key={type} label={t(`source.${type}` as TranslationKey)} selected={value === type} onPress={() => onChange(type)} />
      ))}
    </View>
  );
}
