import type { Story } from './types';

// The web app streams only: browsers can't reliably keep large audio files offline.
export type DownloadEntry = { story: Story; uri: string; bytes: number; dataSaver: boolean; savedAt: string };

export const downloadsSupported = false;

export async function listDownloads(): Promise<Record<string, DownloadEntry>> {
  return {};
}

export async function localUri(_storyId: string): Promise<string | null> {
  return null;
}

export async function downloadStory(_story: Story, _dataSaver: boolean): Promise<DownloadEntry> {
  throw new Error('Downloads are available in the mobile app.');
}

export async function removeDownload(_storyId: string) {}
