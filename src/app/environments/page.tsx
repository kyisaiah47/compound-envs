import Link from "next/link";
import Reveal from "@/components/Reveal";
import { Chip, Legend, Mk, SecHead, Shell, ViewHead } from "@/components/Shell";
import { getEnvironments, scoredCount, totals } from "@/lib/data";

export const dynamic = "force-static";
export const metadata = { title: "Environments" };

export default function EnvironmentsPage() {
  const envs = getEnvironments();
  const all = totals(envs);
  const widest = [...envs].sort((a, b) => b.counts.cheats - a.counts.cheats).slice(0, 6);

  return (
    <Shell
      active="environments"
      envs={envs}
      claim={
        <>
          {all.environments} environments are resettable and gradable. Each one is a real product with seeded state,
          named work, and guards that read the database rather than the transcript.
        </>
      }
      stamps={
        <>
          <span className="stamp">Guards <b>{all.guards}</b></span>
          <span className="stamp">Cheats <b>{all.cheats}</b></span>
        </>
      }
      rail={
        <>
          <div className="grp">
            <h3>What an environment holds</h3>
            <ol className="steps">
              <li><b>Seeded state</b><span>Rows a real account would already have, including the ones that make the task hard.</span></li>
              <li><b>A task book</b><span>Concrete work, each task naming the route it goes through and the tables it writes.</span></li>
              <li><b>Named cheats</b><span>The shortcuts that produce a correct screen over wrong rows.</span></li>
              <li><b>Guards</b><span>State checks, one per cheat plus the ones the task itself requires.</span></li>
            </ol>
          </div>
          <div className="grp">
            <h3>What the states mean</h3>
            <Legend />
          </div>
          <div className="grp">
            <h3>Deepest cheat books</h3>
            <ul className="facts">
              {widest.map((env) => (
                <li key={env.product}>
                  <span>{env.product}</span>
                  <b>{env.counts.cheats}</b>
                </li>
              ))}
            </ul>
          </div>
        </>
      }
    >
      <ViewHead
        kick="Register"
        icon="stack"
        title="The environments, and what each one can prove"
        src={
          <>
            <span><b>schema</b> compound-evals/results@1</span>
            <span><b>read</b> envs/*/results.json</span>
            <span><b>suite</b> adversarial/prove_graders.py</span>
          </>
        }
      >
        A verdict of gradable means the adversarial suite ran every named cheat against its own guard and the guard
        refused it. Graders reads expectations held over expectations declared. A row is a link to that
        environment&apos;s task book.
      </ViewHead>

      <Reveal as="section" className="sec">
        <SecHead title="Register" say="Sorted by product name." count={`${envs.length} environments`} />
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Environment</th>
                <th>Verdict</th>
                <th className="r">Tasks</th>
                <th className="r">Browser</th>
                <th className="r">Guards</th>
                <th className="r">Cheats</th>
                <th className="r">Graders</th>
                <th className="r">Findings</th>
                <th className="r">Score</th>
              </tr>
            </thead>
            <tbody>
              {envs.map((env) => {
                const scored = scoredCount(env);
                const open = env.defects.filter((d) => !d.fixed).length;
                return (
                  <tr key={env.product}>
                    <td>
                      <Link className="nm" href={`/${env.product}`}>
                        <Mk slug={env.product} />
                        <span>{env.product}</span>
                        <small>{env.title}</small>
                      </Link>
                    </td>
                    <td>
                      <Chip tone={env.verdict === "gradable" ? "held" : "caught"}>{env.verdict}</Chip>
                    </td>
                    <td className="fig">{env.tasks.length}</td>
                    <td className="fig">{env.counts.browser_tasks}</td>
                    <td className="fig">{env.counts.guards}</td>
                    <td className="fig">{env.counts.cheats}</td>
                    <td className="fig">{env.suite.expectations_held}/{env.suite.expectations_total}</td>
                    <td className="fig">{open ? `${open} open` : `${env.defects.length} closed`}</td>
                    <td className={scored ? "score held" : "score unrun"}>{scored ? `${scored}/${env.tasks.length}` : "unrun"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Reveal>

      <Reveal as="section" className="sec">
        <SecHead
          title="What the environments refuse to grade"
          say="Routes that look task-shaped and write nothing a guard can read."
          count={`${all.notGradable} recorded`}
        />
        <p className="note">
          A route that writes no row cannot be graded by reading rows. These are named in each environment rather than
          dropped, so the task book states what it left out and why.
        </p>
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Environment</th>
                <th>Not gradable</th>
                <th>Why it is out</th>
              </tr>
            </thead>
            <tbody>
              {envs.flatMap((env) =>
                env.not_gradable.slice(0, 1).map((ng) => (
                  <tr key={`${env.product}/${ng.what}`}>
                    <td>
                      <Link className="nm" href={`/${env.product}`}>
                        <Mk slug={env.product} />
                        <span>{env.product}</span>
                        <small>{env.not_gradable.length} recorded</small>
                      </Link>
                    </td>
                    <td className="mn">{ng.what}</td>
                    <td>{ng.why}</td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
      </Reveal>
    </Shell>
  );
}
