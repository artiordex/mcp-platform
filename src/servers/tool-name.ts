import { createHash } from 'node:crypto';

export function namespacedToolName(
  namespace: string,
  serverId: string,
  toolName: string,
): string {
  const sourceName = `${namespace}_${serverId}_${toolName}`;
  const normalized = sourceName.replace(/[^A-Za-z0-9_-]/g, '_');
  if (normalized.length <= 64) {
    return normalized;
  }

  const hash = createHash('sha256').update(sourceName).digest('hex').slice(0, 10);
  return `${normalized.slice(0, 53)}_${hash}`;
}
