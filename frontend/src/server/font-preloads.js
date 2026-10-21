// Preload only the local unicode-range slices used by the server-rendered text.
export function createFontPreloader(css) {
  const subsets = [
    ...css.matchAll(
      /src:\s*url\(\.\/([^)]*)\)[^;]*;\s*unicode-range:\s*([^;]*);/g,
    ),
  ].map(([, file, range]) => ({
    file,
    ranges: range.split(",").map((item) => {
      const [start, end = start] = item.trim().replace(/^U\+/i, "").split("-");
      return [parseInt(start, 16), parseInt(end, 16)];
    }),
  }));
  return (html, chats) => {
    const text =
      html.replace(/<[^>]*>/g, "") + chats.map((chat) => chat.title).join("");
    const points = [
      ...new Set([...text].map((character) => character.codePointAt(0))),
    ];
    return subsets
      .filter(({ ranges }) =>
        points.some((point) =>
          ranges.some(([start, end]) => point >= start && point <= end),
        ),
      )
      .map(
        ({ file }) =>
          `<link rel="preload" as="font" type="font/woff2" href="/fonts/pretendard-gov/${file}" crossorigin>`,
      )
      .join("\n");
  };
}
