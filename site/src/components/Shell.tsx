import Link from "next/link";
import ThemeSwitch from "./Theme";
import type { Environment } from "@/lib/data";

function Mark() {
  return <span className="marks"><img className="mk mk-dark" src="/compound-mark.svg" alt="" /><img className="mk mk-light" src="/compound-mark-plate.svg" alt="" /></span>;
}

export default function Shell({ active, envs, children }: { active: "evals" | "environments" | string; envs: Environment[]; children: React.ReactNode }) {
  const taskCount = envs.reduce((n, e) => n + e.tasks.length, 0);
  const lastRun = envs.map((e) => e.suite?.last_run).filter(Boolean).sort().at(-1) || "never";
  return <>
    <header className="top">
      <div className="top-in">
        <span className="brand"><Mark /><span>Compound</span><em>EVALS</em></span>
        <div className="folio"><span>SUITE <b>{taskCount.toLocaleString()} tasks</b></span><span>LAST PROVED <b>{lastRun}</b></span></div>
        <span className="live"><i className="dot" />PUBLIC RECORD</span><ThemeSwitch />
      </div>
      <nav className="tabs" aria-label="Evals surfaces">
        <Link href="/evals" data-on={active === "evals"}><Mark />Evals</Link>
        <Link href="/environments" data-on={active === "environments"}>Environments</Link>
      </nav>
    </header>
    <main className="shell">
      <nav className="rail" aria-label="Environment index">
        <h5>THE MEASURE</h5>
        <ul>
          <li><Link href="/evals" data-on={active === "evals"}>Model results</Link></li>
          <li><Link href="/environments" data-on={active === "environments"}>Environment register</Link></li>
        </ul>
        <h5>PRODUCT ENVIRONMENTS</h5>
        <ul>{envs.map((env) => <li key={env.product}><Link href={`/${env.product}`} data-on={active === env.product}><span className="l">{env.product}</span><span className="n">{env.tasks.length}</span></Link></li>)}</ul>
        <div className="gap" />
        <h5>THIS SITE READS</h5>
        <p className="why">versioned results.json records<br /><b>written by the grader suites</b></p>
      </nav>
      <section className="river">{children}</section>
    </main>
  </>;
}

export function ViewHead({ title, children, src }: { title: string; children: React.ReactNode; src?: React.ReactNode }) {
  return <div className="vh"><h1>{title}</h1><p>{children}</p>{src ? <div className="src">{src}</div> : null}</div>;
}
export function Reads({ children }: { children: React.ReactNode }) { return <div className="reads">{children}</div>; }
export function Read({ label, children, working }: { label: string; children: React.ReactNode; working?: React.ReactNode }) {
  return <div className="read"><div className="k">{label}</div><p className="s">{children}</p>{working ? <p className="w">{working}</p> : null}</div>;
}
export function Band({ children, note }: { children: React.ReactNode; note?: React.ReactNode }) { return <div className="band">{children}{note ? <s>{note}</s> : null}<i /></div>; }
export function Chip({ tone, children }: { tone?: string; children: React.ReactNode }) { return <span className={`chip ${tone || "q"}`}>{children}</span>; }
export function Empty({ children }: { children: React.ReactNode }) { return <div className="void">{children}</div>; }
