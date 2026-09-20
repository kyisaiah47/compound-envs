/* THE COMPOUND LABS MARK, INLINE. The isometric cube: a stack of unit cubes in three tones of
 * one grey, white on every top face, #d8d8d8 on every right face, #b0b0b0 on every left face.
 * The light comes from one direction and never moves. That construction is why the register
 * carries no hue of its own, and why the only colour on the page is each product's own mark.
 *
 * It is inline rather than an <img> so the faces can be addressed on hover; globals.css
 * addresses them by their fill rather than by position, because reordering the paths would
 * paint the stack wrong.
 *
 * ⛔ THE DRAWING IS NOT TYPED HERE, AND MUST NEVER BE AGAIN. src/icons/mark.generated.ts is
 * written by compound-ops/brand/app-icons/sync.mjs out of the registry file
 * compound-ops/brand/app-icons/icons/compound-portfolio.svg, which is the SAME file the browser tab
 * (src/app/icon.svg) and the product tile on the studio site are fed from. Change the mark
 * there and run that one command; a second drawing here is how scriptprobe's header came to
 * paint a circle its own tab icon does not contain.
 */
import { MARK_INNER, MARK_VIEWBOX } from '@/icons/mark.generated';

export default function Mark({ className = 'mark' }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox={MARK_VIEWBOX}
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: MARK_INNER }}
    />
  );
}
