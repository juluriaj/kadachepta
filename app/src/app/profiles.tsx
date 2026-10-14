import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { useState } from 'react';
import { Alert, Platform, Pressable, ScrollView, View } from 'react-native';

import { PinPad } from '@/components/ParentGate';
import { Avatar, Button, Screen, Text, useColors } from '@/components/ui';
import { useI18n } from '@/lib/i18n';
import { useSession, type Profile } from '@/lib/session';
import { radius, space } from '@/lib/theme';

function confirm(message: string): Promise<boolean> {
  if (Platform.OS === 'web') return Promise.resolve(window.confirm(message));
  return new Promise((resolve) => Alert.alert('', message, [
    { text: 'Cancel', style: 'cancel', onPress: () => resolve(false) },
    { text: 'OK', style: 'destructive', onPress: () => resolve(true) },
  ]));
}

// "Who's listening?" Leaving a child profile for another profile needs the parent PIN (when one is set).
// Anyone can sign the device out, without the PIN: it shows nothing private and needs the password to undo.
export default function Profiles() {
  const { t } = useI18n();
  const colors = useColors();
  const { household, profile: current, selectProfile, signOut } = useSession();
  const [pending, setPending] = useState<Profile | null>(null);

  const choose = async (profile: Profile) => {
    const leavingChild = current?.kind === 'child' && current.id !== profile.id;
    if (leavingChild && household?.household.hasParentPin) {
      setPending(profile);
      return;
    }
    await selectProfile(profile.id);
    router.replace('/(tabs)');
  };

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ flexGrow: 1, justifyContent: 'center', gap: space.xxl, paddingVertical: space.xxl }}>
        <Text variant="display" style={{ textAlign: 'center' }} accessibilityRole="header">{t('profiles.who')}</Text>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: space.xl }}>
          {(household?.profiles ?? []).map((profile) => (
            <Pressable key={profile.id} onPress={() => void choose(profile)} accessibilityRole="button" accessibilityLabel={profile.name}
              style={({ pressed }) => ({ alignItems: 'center', gap: space.sm, width: 120, padding: space.md, borderRadius: radius.lg,
                backgroundColor: pressed ? colors.surfaceAlt : 'transparent',
                borderWidth: current?.id === profile.id ? 2 : 0, borderColor: colors.primary })}>
              <Avatar avatar={profile.avatar} size={84} />
              <Text variant="heading" numberOfLines={1}>{profile.name}</Text>
              <Text variant="small" muted>{profile.kind === 'child' && profile.ageBand ? t(`age.${profile.ageBand}`) : t('profiles.adult')}</Text>
            </Pressable>
          ))}
        </View>
        <Button kind="ghost" title={t('family.signOut')} style={{ alignSelf: 'center' }}
          icon={<Ionicons name="log-out-outline" size={18} color={colors.primary} />}
          onPress={() => void confirm(t('profiles.signOutConfirm')).then((ok) => { if (ok) void signOut(); })} />
      </ScrollView>
      <PinPad visible={!!pending} onCancel={() => setPending(null)} onDone={async () => {
        const target = pending!;
        setPending(null);
        await selectProfile(target.id);
        router.replace('/(tabs)');
      }} />
    </Screen>
  );
}
