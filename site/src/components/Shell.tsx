import Link from "next/link";
import type { Environment } from "@/lib/data";

function Mark() {
  return <img className="eval-mark" src="/eval-mark.svg" alt="" />;
}

export default function Shell({ active, envs, children }: { active: "evals" | "environments" | string; envs: Environment[]; children: React.ReactNode }) {
  const taskCount = envs.reduce((n, e) => n + e.tasks.length, 0);
  const lastRun = envs.map((e) => e.suite?.last_run).filter(Boolean).sort().at(-1) || "never";
  return <div className="site">
    <header className="mast">
      <div className="mast-main">
        <Link href="/evals" className="identity"><Mark /><span>Compound Evals</span></Link>
        <nav className="nav" aria-label="Evals surfaces">
          <Link href="/evals" data-on={active === "evals"}>Results</Link>
          <Link href="/environments" data-on={active === "environments"}>Environments</Link>
        </nav>
        <span className="status"><i />PUBLIC MEASUREMENT</span>
      </div>
      <div className="tape" aria-label="Suite status">
        <span><b>{taskCount.toLocaleString()}</b> TASKS READY</span>
        <span><b>{lastRun}</b> LAST PROVED</span>
        <span>RESET → RUN → GRADE → PUBLISH</span>
      </div>
    </header>
    <main className="canvas">
      <section className="river">{children}</section>
      <aside className="index" aria-label="Environment index">
        <div className="index-head"><span>ENVIRONMENT INDEX</span><b>{envs.length.toString().padStart(2, "0")}</b></div>
        <div className="index-list">{envs.map((env, i) => <Link key={env.product} href={`/${env.product}`} data-on={active === env.product}><span className="ordinal">{String(i + 1).padStart(2, "0")}</span><span>{env.product}</span><b>{env.tasks.length}</b></Link>)}</div>
      </aside>
    </main>
    <footer className="foot"><span>Compound Evals</span><span>Every score carries its environment.</span><span>Built by Compound Labs</span></footer>
  </div>;
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
