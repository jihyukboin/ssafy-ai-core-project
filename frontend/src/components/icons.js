const paths = {
  panel: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>',
  edit: '<path d="M12 4H6a3 3 0 0 0-3 3v11a3 3 0 0 0 3 3h11a3 3 0 0 0 3-3v-6M15 4l5 5M10 14l-1 4 4-1L21 9a2.8 2.8 0 0 0-4-4z"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  arrowUp: '<path d="M12 20V4m-6 6 6-6 6 6"/>',
  trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
  chat: '<path d="M21 11.5a9 9 0 1 0-4 7.5l4 1-1-4a9 9 0 0 0 1-4z"/>',
  copy: '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M15 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h3"/>',
  like: '<path d="M7 10 12 3a2 2 0 0 1 2 2l-1 5h6a2 2 0 0 1 2 2l-2 7a2 2 0 0 1-2 2H7M3 10h4v11H3z"/>',
  dislike:
    '<path d="m7 14 5 7a2 2 0 0 0 2-2l-1-5h6a2 2 0 0 0 2-2l-2-7a2 2 0 0 0-2-2H7M3 3h4v11H3z"/>',
  refresh: '<path d="M20 8a8 8 0 1 0 0 8m0-13v5h-5"/>',
  volume:
    '<path d="M11 4 5 9H2v6h3l6 5zM15 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>',
};
export const icon = (name) =>
  `<svg class="block size-[20px] shrink-0 fill-none stroke-current [stroke-width:1.65] [stroke-linecap:round] [stroke-linejoin:round]" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.chat}</svg>`;
export function renderIcons(html) {
  return html.replace(
    /<(button|span)\b((?:"[^"]*"|'[^']*'|[^'">])*)>\s*<\/\1\s*>/g,
    (match, tag, attributes) => {
      const name = attributes.match(/\bdata-icon="([^"]+)"/)?.[1];
      return name ? `<${tag}${attributes}>${icon(name)}</${tag}>` : match;
    },
  );
}
