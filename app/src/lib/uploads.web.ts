import { resumableUpload, type Progress, type Purpose } from './uploads.shared';

export type LocalFile = { uri: string; name: string; size?: number | null; file?: Blob | null };

// Web: slice the File (or the recorder's blob URL) into chunks.
export async function uploadFile(source: LocalFile, purpose: Purpose, onProgress?: Progress): Promise<string> {
  const blob = source.file ?? (await (await fetch(source.uri)).blob());
  return resumableUpload({
    name: source.name, size: blob.size, purpose, onProgress,
    read: async (offset, length) => blob.slice(offset, offset + length),
    send: (url, init) => fetch(url, { ...init, credentials: 'same-origin' } as RequestInit),
  });
}
