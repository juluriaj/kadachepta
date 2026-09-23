import { router } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, View } from 'react-native';

import { Button, Field, Screen, Text, useColors } from '@/components/ui';
import { api, ApiError } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { useSession } from '@/lib/session';
import { radius, space } from '@/lib/theme';

type Step = 'email' | 'code' | 'staff' | 'mfa';

export default function SignIn() {
  const { t, language, setLanguage } = useI18n();
  const colors = useColors();
  const { signIn, session, refresh } = useSession();
  const [step, setStep] = useState<Step>(session.mfaRequired || session.mfaEnrollmentRequired ? 'mfa' : 'email');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [secret, setSecret] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  const finish = (result: { mfaRequired?: boolean; mfaEnrollmentRequired?: boolean }) => run(async () => {
    if (result.mfaEnrollmentRequired) {
      const setup = await api<{ secret: string }>('/api/auth/totp/setup', { method: 'POST', body: {}, profile: false });
      setSecret(setup.secret);
      setStep('mfa');
    } else if (result.mfaRequired) {
      setStep('mfa');
    } else {
      router.replace('/');
    }
  });

  return (
    <Screen>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ flexGrow: 1, justifyContent: 'center', gap: space.xl, paddingVertical: space.xxl,
          maxWidth: 440, width: '100%', alignSelf: 'center' }} keyboardShouldPersistTaps="handled">
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md }}>
            <View style={{ width: 48, height: 48, borderRadius: radius.md, backgroundColor: colors.primary, alignItems: 'center',
              justifyContent: 'center' }}>
              <Text variant="title" color={colors.onPrimary}>క</Text>
            </View>
            <View>
              <Text variant="heading">కథాచెప్టా</Text>
              <Text variant="small" muted>{t('app.tagline')}</Text>
            </View>
            <Pressable onPress={() => setLanguage(language === 'en' ? 'te' : 'en')} style={{ marginLeft: 'auto', padding: space.sm }}
              accessibilityRole="button" accessibilityLabel="Change language">
              <Text variant="label" color={colors.primary}>{language === 'en' ? 'తెలుగు' : 'English'}</Text>
            </Pressable>
          </View>

          {step === 'email' || step === 'code' ? (
            <View style={{ gap: space.lg }}>
              <Text variant="display">{t('signin.title')}</Text>
              <Text muted>{step === 'email' ? t('signin.subtitle') : t('signin.codeSent', { email })}</Text>
              {step === 'email' ? (
                <>
                  <Field label={t('signin.email')} value={email} onChangeText={setEmail} autoCapitalize="none" autoComplete="email"
                    keyboardType="email-address" inputMode="email" onSubmitEditing={() => void sendCode()} />
                  <Button title={t('signin.sendCode')} loading={busy} disabled={!email.includes('@')} onPress={() => void sendCode()} />
                </>
              ) : (
                <>
                  <Field label={t('signin.code')} value={code} onChangeText={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))}
                    keyboardType="number-pad" autoComplete="one-time-code" textContentType="oneTimeCode" maxLength={6} />
                  <Button title={t('signin.verify')} loading={busy} disabled={code.length !== 6}
                    onPress={() => run(async () => finish(await signIn({ email, code })))} />
                  <Button title={t('signin.changeEmail')} kind="ghost" onPress={() => { setStep('email'); setCode(''); }} />
                </>
              )}
            </View>
          ) : null}

          {step === 'staff' ? (
            <View style={{ gap: space.lg }}>
              <Text variant="title">{t('signin.staffTitle')}</Text>
              <Field label={t('signin.username')} value={username} onChangeText={setUsername} autoCapitalize="none" autoComplete="username" />
              <Field label={t('signin.password')} value={password} onChangeText={setPassword} secureTextEntry autoComplete="password"
                onSubmitEditing={() => run(async () => finish(await signIn({ username, password })))} />
              <Button title={t('signin.verify')} loading={busy} disabled={!username || !password}
                onPress={() => run(async () => finish(await signIn({ username, password })))} />
              <Button title={t('common.back')} kind="ghost" onPress={() => setStep('email')} />
            </View>
          ) : null}

          {step === 'mfa' ? (
            <View style={{ gap: space.lg }}>
              <Text variant="title">{t('signin.staffTitle')}</Text>
              {secret ? (
                <Text muted>Add this key to your authenticator app, then enter the code it shows: <Text selectable>{secret}</Text></Text>
              ) : <Text muted>{t('signin.mfa')}</Text>}
              <Field label={t('signin.code')} value={code} onChangeText={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))}
                keyboardType="number-pad" autoComplete="one-time-code" maxLength={6} />
              <Button title={t('signin.verify')} loading={busy} disabled={code.length !== 6} onPress={() => run(async () => {
                await api('/api/auth/totp/verify', { method: 'POST', body: { code }, profile: false });
                await refresh();
                router.replace('/');
              })} />
            </View>
          ) : null}

          {error ? <Text color={colors.danger} accessibilityLiveRegion="polite">{error}</Text> : null}

          {step === 'email' || step === 'code' ? (
            <Button title={t('signin.staff')} kind="ghost" onPress={() => { setError(null); setStep('staff'); }} />
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </Screen>
  );

  async function sendCode() {
    await run(async () => {
      await api('/api/auth/otp/request', { method: 'POST', body: { email: email.trim() }, profile: false });
      setStep('code');
    });
  }
}
