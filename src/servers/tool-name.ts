/**
 * 파일명: tool-name.ts
 * 경로: src/servers/tool-name.ts
 * 목적: MCP 게이트웨이에서 하위 도구 식별자 충돌을 방지하기 위한 네임스페이스 정규화를 수행함
 * 작성자: AI전략팀
 * 작성일: 2026-09-30
 * 수정일: 2026-09-30
 */

import { createHash } from 'node:crypto';

/**
 * 네임스페이스와 서버 식별자를 접두사로 결합하여 MCP 표준 길이(64자) 내의 고유 도구명을 생성함
 *
 * @param namespace 도구 그룹 네임스페이스임
 * @param serverId 하위 서버 식별자임
 * @param toolName 원본 도구명임
 * @returns 64자 이내로 정규화 및 해시 축약된 안전한 도구명을 반환함
 */
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

  // NOTE: MCP 명세상 도구명 최대 길이가 64자이므로 초과 시 해시 10자를 결합해 충돌을 방지함
  const hash = createHash('sha256').update(sourceName).digest('hex').slice(0, 10);
  return `${normalized.slice(0, 53)}_${hash}`;
}
