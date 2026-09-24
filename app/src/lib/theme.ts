// Calm, warm palette. "day" is the default; "night" is bedtime mode (low blue light, low contrast glare).
export const palette = {
  day: {
    background: '#F7F6F1',
    surface: '#FFFEFA',
    surfaceAlt: '#EEF1EA',
    text: '#243028',
    muted: '#66736B',
    primary: '#315747',
    onPrimary: '#FFFFFF',
    accent: '#DC7452',
    onAccent: '#FFFFFF',
    border: '#E1E4DC',
    danger: '#A24E3F',
    success: '#28734D',
    overlay: 'rgba(20, 26, 22, 0.55)',
  },
  night: {
    background: '#12162A',
    surface: '#1B2038',
    surfaceAlt: '#232946',
    text: '#EFE3CC',
    muted: '#A59C8A',
    primary: '#E9B872',
    onPrimary: '#1B1B1B',
    accent: '#E9B872',
    onAccent: '#1B1B1B',
    border: '#2E3456',
    danger: '#E08A76',
    success: '#8FC7A3',
    overlay: 'rgba(0, 0, 0, 0.6)',
  },
};

export type Colors = typeof palette.day;

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 };
export const radius = { sm: 8, md: 12, lg: 18, pill: 999 };

export const fonts = {
  body: 'DMSans_400Regular',
  medium: 'DMSans_500Medium',
  bold: 'DMSans_700Bold',
  telugu: 'NotoSansTelugu_400Regular',
  teluguBold: 'NotoSansTelugu_700Bold',
};

// Text that may contain Telugu script gets the Telugu font; Latin text keeps DM Sans.
export function fontFor(text: string | null | undefined, weight: 'regular' | 'bold' = 'regular') {
  const hasTelugu = /[ఀ-౿]/.test(text ?? '');
  if (hasTelugu) return weight === 'bold' ? fonts.teluguBold : fonts.telugu;
  return weight === 'bold' ? fonts.bold : fonts.body;
}

export const cover = ['#7C9A86', '#C76D4B', '#6E8EA1', '#827294', '#B08A4E', '#5F8F7A'];
export function coverColor(id: string) {
  let hash = 0;
  for (const ch of id) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return cover[hash % cover.length];
}

// Touch targets stay at least 48dp for small hands and drivers.
export const touch = 48;
