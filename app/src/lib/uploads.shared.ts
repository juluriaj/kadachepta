import { api, ApiError, authHeaders, API_BASE, refreshAfter401 } from './api';

// Resumable uploads: the file goes up in 4 MB chunks; after a dropped connection the upload asks the
// server how much it has and continues from there. Platform files supply the chunk reader.

export type Purpose = 'audio' | 'evidence' | 'sample';
export type Progress = (sent: number, total: number) => void;
export type ChunkReader = (offset: number, length: number) => Promise<Uint8Array | Blob>;
type UploadInfo = { id: string; receivedBytes: number; complete: boolean; chunkSize: number };

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function resumableUpload(
  { name, size, read, purpose, onProgress, send }: {
    name: string; size: number; read: ChunkReader; purpose: Purpose; onProgress?: Progress;
    send: (url: string, init: { method: string; headers: Record<string, string>; body: Uint8Array | Blob }) => Promise<Response>;
  }): Promise<string> {
  const created = await api<UploadInfo>('/api/uploads', { method: 'POST', body: { filename: name, size, purpose }, profile: false });
  let offset = created.receivedBytes;
  let failures = 0;
  while (offset < size) {
    const length = Math.min(created.chunkSize, size - offset);
    try {
      const body = await read(offset, length);
      const headers = { 'Content-Type': 'application/octet-stream', ...(await authHeaders()) };
      let response = await send(`${API_BASE}/api/uploads/${created.id}?offset=${offset}`, { method: 'PUT', headers, body });
      if (response.status === 401 && (await refreshAfter401())) {
        response = await send(`${API_BASE}/api/uploads/${created.id}?offset=${offset}`,
          { method: 'PUT', headers: { ...headers, ...(await authHeaders()) }, body });
      }
      const data = await response.json().catch(() => ({}));
      if (response.status === 409 && typeof data.receivedBytes === 'number') {
        offset = data.receivedBytes; // the server is behind or ahead of us: continue from its position
        continue;
      }
      if (!response.ok) throw new ApiError(response.status, data, 'PUT', `/api/uploads/${created.id}`);
      offset = data.receivedBytes;
      failures = 0;
      onProgress?.(offset, size);
    } catch (error) {
      if (error instanceof ApiError && error.status < 500 && error.status !== 408) throw error;
      failures += 1;
      if (failures > 8) throw error;
      await sleep(Math.min(30_000, 1000 * 2 ** failures)); // offline or flaky: back off, then resume
      const status = await api<UploadInfo>(`/api/uploads/${created.id}`, { profile: false }).catch(() => null);
      if (status) offset = status.receivedBytes;
    }
  }
  return created.id;
}
