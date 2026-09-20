"use client";

import { useEffect, useState } from "react";

export const BOOT = `(function(){try{var q=new URLSearchParams(location.search).get('theme');var t=q||localStorage.getItem('compound-evals-theme');if(t==='light')document.documentElement.dataset.theme='light'}catch(e){}})()`;

export default function ThemeSwitch() {
  const [light, setLight] = useState(false);
  useEffect(() => setLight(document.documentElement.dataset.theme === "light"), []);
  return <button className="act theme" onClick={() => {
    const next = !light;
    setLight(next);
    if (next) document.documentElement.dataset.theme = "light";
    else delete document.documentElement.dataset.theme;
    localStorage.setItem("compound-evals-theme", next ? "light" : "dark");
  }} aria-label="Switch colour theme">{light ? "DARK" : "LIGHT"}</button>;
}
