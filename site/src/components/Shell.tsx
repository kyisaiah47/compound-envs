import Link from "next/link";
import Mark from "@/components/Mark";
import Ph from "@/components/Ph";
import { type Environment, lastProved, scoredCount, totals } from "@/lib/data";

/** A product's own mark, out of the estate's icon registry. Every row naming a product carries it. */
export function Mk({ slug }: { slug: string }) {
  return <img className="mk" src={`/marks/${slug}.svg`} alt="" width={18} height={18} />;
}

/** The rail a model was driven on. public/rails/codex-headless.svg is a byte copy of the
 *  estate's own Codex CLI logo, stillshipping/public/logos/tool-codex-cli.svg. */
export function RailMk({ rail }: { rail: string }) {
  if (rail !== "codex-headless") return null;
  return <img className="mk" src="/rails/codex-headless.svg" alt="" width={18} height={18} />;
}

export function Shell({
  active,
  envs,
  claim,
  stamps,
  rail,
  children,
}: {
  active: string;
  envs: Environment[];
  claim: React.ReactNode;
  stamps?: React.ReactNode;
  rail: React.ReactNode;
  children: React.ReactNode;
}) {
  const all = totals(envs);
  const proved = lastProved(envs);
  const unrun = all.tasks - all.scored;

  return (
    <>
      <header className="mast">
        <Link href="/" className="brand">
          <Mark />
          <b>Compound Evals</b>
        </Link>
        <nav className="nav" aria-label="Evals surfaces">
          <Link href="/" className={active === "scorecard" ? "on" : undefined}>
            <Ph n="squares-four" />
            Scorecard
          </Link>
          <Link href="/environments" className={active === "environments" ? "on" : undefined}>
            <Ph n="stack" />
            Environments
          </Link>
        </nav>
        <div className="mast-r">
          <span className="pulse">
            <i />
            <span>Graders proved</span>
            <b>{all.held}/{all.expected}</b>
          </span>
          <span className="pulse n">{proved}</span>
        </div>
      </header>

      <div className="folio" aria-label="What the suite can state today">
        <span><Ph n="flask" /><b>{all.environments}</b> environments</span>
        <span><Ph n="list-checks" /><b>{all.tasks}</b> tasks</span>
        <span><Ph n="shield-check" /><b>{all.guards}</b> guards</span>
        <span><Ph n="mask-happy" /><b>{all.cheats}</b> named cheats</span>
        <span><Ph n="seal-check" /><b>{all.scored}</b> scores recorded</span>
        <span className="grow"><Ph n="circle-dashed" /><b>{unrun}</b> tasks never run</span>
      </div>

      <div className="band">
        <p>{claim}</p>
        {stamps ? <div className="ctl">{stamps}</div> : null}
        <div className="prog" aria-hidden="true"><i /></div>
      </div>

      <main className="cols">
        <aside className="rail" aria-label="Environment index">
          <div className="grp">
            <h3>Environments</h3>
            {envs.map((env) => {
              const scored = scoredCount(env);
              return (
                <Link key={env.product} href={`/${env.product}`} className={`it${active === env.product ? " on" : ""}`}>
                  <img className="mk" src={`/marks/${env.product}.svg`} alt="" width={16} height={16} />
                  <span className="nm">{env.product}</span>
                  <span className="ct">{scored ? `${scored}/${env.tasks.length}` : env.tasks.length}</span>
                </Link>
              );
            })}
          </div>
          <div className="grp">
            <h3>Reading the index</h3>
            <p className="who">
              The figure beside an environment is its tasks. Where a run exists it reads scored over total.
            </p>
          </div>
        </aside>

        <section className="river">{children}</section>

        <aside className="rr">{rail}</aside>
      </main>

      <footer className="foot">
        <span className="sig"><Mark className="mark" />Compound Evals</span>
        <span>Every score carries the environment that produced it.</span>
        <a href="https://thecompound.tech">Compound Labs</a>
        <span className="end n">Graders proved {proved}</span>
      </footer>
    </>
  );
}

export function ViewHead({
  kick,
  icon,
  title,
  children,
  src,
}: {
  kick: string;
  icon: string;
  title: string;
  children?: React.ReactNode;
  src?: React.ReactNode;
}) {
  return (
    <div className="vh">
      <p className="kick"><Ph n={icon} />{kick}</p>
      <h1>{title}</h1>
      {children ? <p>{children}</p> : null}
      {src ? <div className="src">{src}</div> : null}
    </div>
  );
}

export function SecHead({ title, say, count }: { title: string; say?: string; count?: React.ReactNode }) {
  return (
    <div className="sec-h">
      <h2>{title}</h2>
      {say ? <p className="say">{say}</p> : null}
      {count ? <span className="ct">{count}</span> : null}
    </div>
  );
}

export function Chip({ tone, children }: { tone?: string; children: React.ReactNode }) {
  return <span className={`chip ${tone || ""}`.trim()}>{children}</span>;
}

export function Legend() {
  return (
    <ul className="legend">
      <li><i className="i-held" /><span><b>Held</b>the guard passed on the state the model left</span></li>
      <li><i className="i-caught" /><span><b>Caught</b>the guard refused it, and names what it found</span></li>
      <li><i className="i-unrun" /><span><b>Unrun</b>no model has been driven through this task</span></li>
    </ul>
  );
}
