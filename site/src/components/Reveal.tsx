'use client';

import { useEffect, useRef, type ReactNode } from 'react';

/* THE ENTRANCE. One stagger, once, on first view, and nothing after it: a row that has been read
 * does not move again. The class lands on an IntersectionObserver rather than a timer, so a band
 * below the fold enters when it is reached rather than having already entered before the reader
 * arrives. Under prefers-reduced-motion the stylesheet gives .rv no transform at all and the
 * class is added immediately, so a screenshot taken after a scroll is always correct. */
export default function Reveal({
  children, delay = 0, as: As = 'div', className, id,
}: {
  children: ReactNode;
  delay?: number;
  as?: 'div' | 'section' | 'aside' | 'li' | 'article' | 'tr';
  className?: string;
  id?: string;
}) {
  const ref = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      el.classList.add('in');
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          window.setTimeout(() => el.classList.add('in'), delay);
          io.unobserve(el);
        }
      },
      { rootMargin: '0px 0px -8% 0px' },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [delay]);
  const cls = className ? `rv ${className}` : 'rv';
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return <As ref={ref as any} className={cls} id={id}>{children}</As>;
}
