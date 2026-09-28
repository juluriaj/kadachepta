import Ionicons from '@expo/vector-icons/Ionicons';
import { useState } from 'react';
import { Pressable, View } from 'react-native';

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

// What is happening with a submission right now and what comes next, so the narrator never has to guess.
export function StageGuide({ stage }: { stage: string }) {
  const { t } = useI18n();
  const colors = useColors();
  const now = `guide.now.${stage}` as TranslationKey;
  if (t(now) === now) return null;
  return (
    <View style={{ gap: space.sm, paddingTop: space.md, borderTopWidth: 1, borderColor: colors.border }}>
      <Text><Text variant="label" color={colors.primary}>{t('guide.now')}: </Text>{t(now)}</Text>
      <Text><Text variant="label" color={colors.primary}>{t('guide.next')}: </Text>{t(`guide.next.${stage}` as TranslationKey)}</Text>
    </View>
  );
}

// The whole journey from recording to published, open by default until the narrator has a story.
export function HowItWorks({ initiallyOpen }: { initiallyOpen: boolean }) {
  const { t } = useI18n();
  const colors = useColors();
  const [open, setOpen] = useState(initiallyOpen);
  return (
    <View style={{ padding: space.md, borderRadius: 14, backgroundColor: colors.surfaceAlt, gap: space.sm }}>
      <Pressable onPress={() => setOpen(!open)} accessibilityRole="button" accessibilityState={{ expanded: open }}
        style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
        <Ionicons name="information-circle-outline" size={20} color={colors.primary} />
        <Text variant="heading" style={{ flex: 1 }}>{t('guide.how')}</Text>
        <Ionicons name={open ? 'chevron-up' : 'chevron-down'} size={18} color={colors.muted} />
      </Pressable>
      {open ? <Text style={{ lineHeight: 24 }}>{t('guide.howSteps')}</Text> : null}
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
