import Link from "next/link";
import { type Environment, lastProved, scoredCount, totals } from "@/lib/data";

/* The estate's one Compound Labs logo, the isometric compound cube, with the single variation
 * this surface earns: the one face the logo already singles out is painted in the Evals accent
 * rather than #1a1a1a. public/evals-mark.svg is generated from
 * compound-ops/brand/compound-labs/logo/compound-labs.svg and every other path in it is
 * byte-identical to that file. */
export function Mark() {
  return <img src="/evals-mark.svg" alt="" width={21} height={21} />;
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
  return (
    <>
      <header className="top">
        <div className="top-in">
          <Link href="/" className="brand">
            <Mark />
            <span>Compound Evals</span>
            <em>Measurement</em>
          </Link>
          <nav className="nav" aria-label="Evals surfaces">
            <Link href="/" data-on={active === "scorecard"}>Scorecard</Link>
            <Link href="/environments" data-on={active === "environments"}>Environments</Link>
          </nav>
          <div className="top-r">
            <span className="live">
              <i />
              <span>Suite held {all.held} of {all.expected}</span>
            </span>
            <span className="live n">{proved}</span>
          </div>
        </div>
      </header>

      <div className="folio" aria-label="Estate totals">
        <span><b>{all.environments}</b> environments</span>
        <span><b>{all.tasks}</b> tasks</span>
        <span><b>{all.guards}</b> guards</span>
        <span><b>{all.cheats}</b> named cheats</span>
        <span className="lit"><b>{all.scored}</b> scores recorded</span>
        <span><b>{all.open}</b> findings open</span>
      </div>

      <div className="bar">
        <p className="bar-said">{claim}</p>
        {stamps ? <div className="bar-ctl">{stamps}</div> : null}
      </div>

      <div className="console">
        <aside className="side" aria-label="Environment index">
          <section>
            <h2>Environments</h2>
            <nav className="idx">
              {envs.map((env) => {
                const scored = scoredCount(env);
                return (
                  <Link key={env.product} href={`/${env.product}`} data-on={active === env.product} className={scored ? "scored" : undefined}>
                    <img src={`/marks/${env.product}.svg`} alt="" width={16} height={16} />
                    <span className="nm">{env.product}</span>
                    <span className="ct">{scored ? `${scored}/${env.tasks.length}` : env.tasks.length}</span>
                  </Link>
                );
              })}
            </nav>
          </section>
          <section>
            <h2>Reading the index</h2>
            <p className="rail-note">
              The figure beside an environment is its tasks. Where a run exists it reads scored over total, and the
              square is lit.
            </p>
          </section>
        </aside>

        <main className="river">{children}</main>

        <aside className="side side-r">{rail}</aside>
      </div>

      <section className="band">
        <div className="band-in">
          <p className="band-lab">The method</p>
          <div className="qa">
            <div>
              <h3>A score is a database read, not a transcript read</h3>
              <p>
                The grader resets the environment to a known state, drives the model through the product&apos;s own
                surface, then queries the rows the product wrote. Nothing reads what the model said it did.
              </p>
            </div>
            <div>
              <h3>Every guard has a named cheat behind it</h3>
              <p>
                Each guard was written against a specific shortcut that produces the right-looking screen and the wrong
                rows. {all.cheats} of those shortcuts are named, and each names the guard that catches it.
              </p>
            </div>
            <div>
              <h3>A task that was never run carries no score</h3>
              <p>
                An unrun cell is grey and says so. It is never printed as a zero, because a zero is a measurement and a
                missing run is not one.
              </p>
            </div>
            <div>
              <h3>The graders are proved before a model touches them</h3>
              <p>
                Each environment ships an adversarial suite that runs every named cheat against its own guard and checks
                the guard refuses it. The suite held {all.held} of {all.expected} expectations on its last run.
              </p>
            </div>
          </div>
        </div>
      </section>

      <footer className="foot">
        <span className="sig">Compound Evals</span>
        <span>Every score carries the environment that produced it.</span>
        <a href="https://thecompound.tech">Compound Labs</a>
        <span className="end n">Suite last proved {proved}</span>
      </footer>
    </>
  );
}

export function ViewHead({
  kick,
  title,
  children,
  src,
}: {
  kick: string;
  title: string;
  children?: React.ReactNode;
  src?: React.ReactNode;
}) {
  return (
    <div className="vh">
      <p className="kick">{kick}</p>
      <h1>{title}</h1>
      {children ? <p>{children}</p> : null}
      {src ? <div className="src">{src}</div> : null}
    </div>
  );
}

export function Head2({ title, say, count }: { title: string; say?: string; count?: React.ReactNode }) {
  return (
    <div className="head2">
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
      <li><i className="i-cheat" /><span><b>Cheat</b>a named shortcut a guard exists to catch</span></li>
      <li><i className="i-open" /><span><b>Open</b>a recorded defect with no fix yet</span></li>
    </ul>
  );
}
