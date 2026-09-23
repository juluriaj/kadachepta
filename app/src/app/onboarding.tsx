import Ionicons from '@expo/vector-icons/Ionicons';
import { useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';

import { Avatar, Button, Chip, Field, Screen, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { LANGUAGE_LABELS, useI18n } from '@/lib/i18n';
import { useSession, type Household } from '@/lib/session';
import { radius, space } from '@/lib/theme';

type Child = { name: string; ageBand: '3-5' | '6-8' | '9-12'; avatar: string };
const MOMENT_ICONS: Record<string, keyof typeof Ionicons.glyphMap> = {
  bedtime: 'moon-outline', drive: 'car-outline', run: 'walk-outline', work: 'laptop-outline', learn: 'school-outline',
};
const KID_AVATARS = ['elephant', 'parrot', 'tiger', 'monkey', 'deer', 'owl'];

export default function Onboarding() {
  const { t, language } = useI18n();
  const colors = useColors();
  const queryClient = useQueryClient();
  const { household, selectProfile } = useSession();
  const [step, setStep] = useState(0);
  const [languages, setLanguages] = useState<string[]>(['te-IN']);
  const [children, setChildren] = useState<Child[]>([]);
  const [draftName, setDraftName] = useState('');
  const [draftBand, setDraftBand] = useState<Child['ageBand']>('3-5');
  const [moments, setMoments] = useState<string[]>(['bedtime', 'drive']);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const options = household?.options;

  const toggle = <T,>(list: T[], value: T) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);

  const addChild = () => {
    if (!draftName.trim()) return;
    setChildren([...children, { name: draftName.trim(), ageBand: draftBand, avatar: KID_AVATARS[children.length % KID_AVATARS.length] }]);
    setDraftName('');
  };

  const finish = async () => {
    setBusy(true);
    setError(null);
    try {
      const allChildren = draftName.trim()
        ? [...children, { name: draftName.trim(), ageBand: draftBand, avatar: KID_AVATARS[children.length % KID_AVATARS.length] }]
        : children;
      const result = await api<Household>('/api/household/onboarding', {
        method: 'POST', profile: false,
        body: { listeningLanguages: languages, uiLanguage: language, children: allChildren, moments },
      });
      // Use the saved household straight away so the next screen never sees stale "not onboarded" data.
      queryClient.setQueryData(['household'], result);
      if (!allChildren.length) await selectProfile(result.profiles.find((p) => p.kind === 'adult')!.id);
      router.replace('/');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ gap: space.xl, paddingVertical: space.xxl, maxWidth: 560, width: '100%', alignSelf: 'center' }}
        keyboardShouldPersistTaps="handled">
        <View style={{ flexDirection: 'row', gap: 6 }} accessibilityLabel={`Step ${step + 1} of 3`}>
          {[0, 1, 2].map((i) => (
            <View key={i} style={{ flex: 1, height: 4, borderRadius: 2, backgroundColor: i <= step ? colors.primary : colors.border }} />
          ))}
        </View>
        <Text variant="label" muted>{t('onboarding.welcome')}</Text>

        {step === 0 ? (
          <View style={{ gap: space.lg }}>
            <Text variant="display">{t('onboarding.languages')}</Text>
            <Text muted>{t('onboarding.languagesHint')}</Text>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
              {(options?.listeningLanguages ?? ['te-IN', 'en-IN', 'hi-IN']).map((code) => (
                <Chip key={code} label={LANGUAGE_LABELS[code] ?? code} selected={languages.includes(code)}
                  onPress={() => setLanguages(languages.includes(code) && languages.length > 1 ? languages.filter((l) => l !== code)
                    : languages.includes(code) ? languages : [...languages, code])} />
              ))}
            </View>
          </View>
        ) : null}

        {step === 1 ? (
          <View style={{ gap: space.lg }}>
            <Text variant="display">{t('onboarding.kids')}</Text>
            <Text muted>{t('onboarding.kidsHint')}</Text>
            {children.map((child, index) => (
              <View key={`${child.name}-${index}`} style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.md,
                borderRadius: radius.md, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border }}>
                <Avatar avatar={child.avatar} size={44} />
                <View style={{ flex: 1 }}>
                  <Text variant="heading">{child.name}</Text>
                  <Text variant="small" muted>{t(`age.${child.ageBand}`)}</Text>
                </View>
                <Pressable onPress={() => setChildren(children.filter((_, i) => i !== index))} hitSlop={12} accessibilityLabel={`Remove ${child.name}`}>
                  <Ionicons name="close-circle-outline" size={24} color={colors.muted} />
                </Pressable>
              </View>
            ))}
            <Field label={t('onboarding.kidName')} value={draftName} onChangeText={setDraftName} onSubmitEditing={addChild} />
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
              {(['3-5', '6-8', '9-12'] as const).map((band) => (
                <Chip key={band} label={t(`age.${band}`)} selected={draftBand === band} onPress={() => setDraftBand(band)} />
              ))}
            </View>
            <Button title={t('onboarding.addKid')} kind="secondary" disabled={!draftName.trim()} onPress={addChild}
              icon={<Ionicons name="add" size={20} color={colors.text} />} />
          </View>
        ) : null}

        {step === 2 ? (
          <View style={{ gap: space.lg }}>
            <Text variant="display">{t('onboarding.moments')}</Text>
            <Text muted>{t('onboarding.momentsHint')}</Text>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
              {(options?.moments ?? Object.keys(MOMENT_ICONS)).map((moment) => (
                <Chip key={moment} label={t(`moment.${moment}` as 'moment.bedtime')} selected={moments.includes(moment)}
                  icon={<Ionicons name={MOMENT_ICONS[moment]} size={16} color={moments.includes(moment) ? colors.onPrimary : colors.text} />}
                  onPress={() => setMoments(toggle(moments, moment))} />
              ))}
            </View>
          </View>
        ) : null}

        {error ? <Text color={colors.danger}>{error}</Text> : null}
        <View style={{ flexDirection: 'row', gap: space.md }}>
          {step > 0 ? <Button title={t('common.back')} kind="secondary" onPress={() => setStep(step - 1)} style={{ flex: 1 }} /> : null}
          <Button title={step < 2 ? t('common.continue') : t('onboarding.finish')} loading={busy} style={{ flex: 2 }}
            onPress={() => (step < 2 ? setStep(step + 1) : void finish())} />
        </View>
      </ScrollView>
    </Screen>
  );
}
