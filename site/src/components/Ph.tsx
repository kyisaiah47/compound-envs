import { PHOSPHOR, type PhName } from '@/icons/phosphor.generated';

/* A Phosphor Regular glyph, inlined. The set is compiled by scripts/build-icons.mjs, so no icon
 * font loads and nothing is fetched at runtime. A name the map does not carry throws at build
 * time rather than painting an empty box on a page nobody opens. */
export default function Ph({ n, className, style }: { n: PhName | string; className?: string; style?: React.CSSProperties }) {
  const inner = PHOSPHOR[n as PhName];
  if (!inner) throw new Error(`no phosphor glyph "${n}" in src/icons`);
  return (
    <svg
      className={className ? `ph ${className}` : 'ph'}
      style={style}
      viewBox="0 0 256 256"
      fill="currentColor"
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: inner }}
    />
  );
}
