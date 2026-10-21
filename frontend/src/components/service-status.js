import { escapeHtml } from "../utils/html.js";
export function serviceStatusHtml(status) {
  if (!status?.ready)
    return escapeHtml(
      status?.message ||
        (!status?.key_configured
          ? "서버의 GMS_KEY 설정을 확인하세요."
          : "기업 메타데이터 색인이 필요합니다. backend에서 python -m rag.index를 실행하세요."),
    );
  return `기업 ${Number(status.companies)}개 · 메타데이터 ${Number(status.counts?.stock_meta)}건 · 문서 ${Number(status.counts?.disclosure_docs)}청크 · 기준 ${escapeHtml(status.price_as_of)}`;
}
