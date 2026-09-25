import { fetch as expoFetch } from 'expo/fetch';
import { File } from 'expo-file-system';

import { resumableUpload, type Progress, type Purpose } from './uploads.shared';

export type LocalFile = { uri: string; name: string; size?: number | null; file?: Blob | null };

// Native: read chunks straight from disk so long recordings never sit in memory.
export async function uploadFile(source: LocalFile, purpose: Purpose, onProgress?: Progress): Promise<string> {
  const file = new File(source.uri);
  const size = source.size || file.size;
  const handle = file.open();
  try {
    return await resumableUpload({
      name: source.name, size, purpose, onProgress,
      read: async (offset, length) => {
        handle.offset = offset;
        return handle.readBytes(length);
      },
      send: (url, init) => expoFetch(url, init as Parameters<typeof expoFetch>[1]) as unknown as Promise<Response>,
    });
  } finally {
    handle.close();
  }
}
