import AsyncStorage from '@react-native-async-storage/async-storage';
import { Directory, File, Paths } from 'expo-file-system';

import { mediaUrl } from './api';
import type { Story } from './types';

// Stories are saved in the app's private documents folder (not visible to other apps) and listed in
// AsyncStorage so the library works offline. Phase 4 ties downloads to the subscription entitlement.
const INDEX = 'kc.downloads';
const folder = () => new Directory(Paths.document, 'downloads');

export type DownloadEntry = { story: Story; uri: string; bytes: number; dataSaver: boolean; savedAt: string };

export const downloadsSupported = true;

export async function listDownloads(): Promise<Record<string, DownloadEntry>> {
  const raw = await AsyncStorage.getItem(INDEX);
  const index: Record<string, DownloadEntry> = raw ? JSON.parse(raw) : {};
  // Drop entries whose file was removed by the OS (low storage) or a reinstall.
  for (const [id, entry] of Object.entries(index)) {
    if (!new File(entry.uri).exists) delete index[id];
  }
  return index;
}

export async function localUri(storyId: string): Promise<string | null> {
  const entry = (await listDownloads())[storyId];
  return entry?.uri ?? null;
}

export async function downloadStory(story: Story, dataSaver: boolean): Promise<DownloadEntry> {
  const source = mediaUrl(dataSaver ? story.audioUrlDataSaver ?? story.audioUrl : story.audioUrl);
  if (!source) throw new Error('This story has no audio to download yet.');
  const dir = folder();
  if (!dir.exists) dir.create({ intermediates: true });
  const target = new File(dir, `${story.id}${dataSaver ? '-ds' : ''}.m4a`);
  if (target.exists) target.delete();
  const file = await File.downloadFileAsync(source, target);
  const entry: DownloadEntry = { story, uri: file.uri, bytes: file.size ?? 0, dataSaver, savedAt: new Date().toISOString() };
  const index = await listDownloads();
  index[story.id] = entry;
  await AsyncStorage.setItem(INDEX, JSON.stringify(index));
  return entry;
}

export async function removeDownload(storyId: string) {
  const index = await listDownloads();
  const entry = index[storyId];
  if (entry) {
    const file = new File(entry.uri);
    if (file.exists) file.delete();
    delete index[storyId];
    await AsyncStorage.setItem(INDEX, JSON.stringify(index));
  }
}
