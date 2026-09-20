"use client";

import { useEffect, type ReactNode } from "react";
import Lenis from "lenis";

/* Smooth scroll through the lenis package, for readers who have not asked for reduced motion.
 *
 * This site stacks two sticky bands, the masthead and the claim bar, so a same-page anchor has to
 * land under both. The offset is measured off the two bands as they are painted rather than
 * written down as a number, and the target is its layout position summed up the offsetParent
 * chain: a row that has not entered yet sits a few pixels low on its entering transform, and a
 * bounding rect read then would land short of where it settles. */
let active: { to: (el: HTMLElement) => void } | null = null;
export const scrollToEl = (el: HTMLElement) => (active ? active.to(el) : el.scrollIntoView());

function stickyOffset(): number {
  let h = 0;
  for (const sel of [".top", ".bar"]) {
    const el = document.querySelector<HTMLElement>(sel);
    if (el && getComputedStyle(el).position === "sticky") h += el.offsetHeight;
  }
  return h + 14;
}

function layoutTop(el: HTMLElement): number {
  let y = 0;
  for (let n: HTMLElement | null = el; n; n = n.offsetParent as HTMLElement | null) y += n.offsetTop;
  return y;
}

export default function LenisProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    /* ⛔ allowNestedScroll IS LOAD BEARING. Lenis cancels every wheel it handles, so without it no
     * nested overflow:auto box can scroll, and this layout has two: the sticky environment index
     * and the sticky method rail. It re-measures the node under the pointer and yields only when
     * that node really can scroll. Never data-lenis-prevent, which traps the wheel over a region
     * that is not currently scrollable. */
    const lenis = new Lenis({ allowNestedScroll: true, autoRaf: true, lerp: 0.35, anchors: false });
    document.documentElement.classList.add("lenis");
    const target = (el: HTMLElement) => Math.max(0, layoutTop(el) - stickyOffset());

    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
      const a = (e.target as HTMLElement | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!a) return;
      const url = new URL(a.href, location.href);
      if (url.origin !== location.origin || url.pathname !== location.pathname || !url.hash) return;
      const el = document.getElementById(decodeURIComponent(url.hash.slice(1)));
      if (!el) return;
      e.preventDefault();
      lenis.scrollTo(target(el));
      history.replaceState(null, "", url.hash);
    };
    document.addEventListener("click", onClick);
    active = { to: (el) => lenis.scrollTo(target(el)) };

    /* The read line under the claim bar: how far down the register the reader is. */
    const bar = document.querySelector<HTMLElement>(".prog i");
    const onScroll = () => {
      if (!bar) return;
      const run = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.transform = `scaleX(${run > 0 ? Math.min(1, window.scrollY / run) : 0})`;
    };
    lenis.on("scroll", onScroll);
    onScroll();

    if (location.hash) {
      const el = document.getElementById(decodeURIComponent(location.hash.slice(1)));
      if (el) requestAnimationFrame(() => lenis.scrollTo(target(el), { immediate: true }));
    }
    return () => {
      document.removeEventListener("click", onClick);
      document.documentElement.classList.remove("lenis");
      active = null;
      lenis.destroy();
    };
  }, []);
  return <>{children}</>;
}
