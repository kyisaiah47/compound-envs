import { notFound } from "next/navigation";
import { Chip, Head2, Legend, Shell, ViewHead } from "@/components/Shell";
import { getEnvironment, getEnvironments, scoredCount, toScore } from "@/lib/data";

export const dynamic = "force-static";

export function generateStaticParams() {
  return getEnvironments().map((env) => ({ product: env.product }));
}

export async function generateMetadata({ params }: { params: Promise<{ product: string }> }) {
  const { product } = await params;
  const env = getEnvironment(product);
  return { title: env ? env.product : "Environment" };
}

export default async function ProductPage({ params }: { params: Promise<{ product: string }> }) {
  const { product } = await params;
  const env = getEnvironment(product);
  if (!env) notFound();

  const envs = getEnvironments();
  const scored = scoredCount(env);
  const open = env.defects.filter((d) => !d.fixed);
  const models = Object.entries(env.models);
  const writes = [...new Set(env.tasks.flatMap((t) => t.writes))];

  return (
    <Shell
      active={env.product}
      envs={envs}
      claim={
        <>
          {env.tasks.length} tasks against{" "}
          <a href={env.product_url} rel="noreferrer">{env.product_url.replace(/^https?:\/\//, "")}</a>, held by{" "}
          {env.counts.guards} guards written against {env.counts.cheats} named cheats.
        </>
      }
      stamps={
        <>
          <Chip tone={env.verdict === "gradable" ? "ok" : "bad"}>{env.verdict}</Chip>
          <span className="stamp">Suite <b>{env.suite.expectations_held}/{env.suite.expectations_total}</b></span>
          <span className="stamp">Scored <b className={scored ? undefined : "off"}>{scored}/{env.tasks.length}</b></span>
        </>
      }
      rail={
        <>
          <section>
            <h2>This environment</h2>
            <ul className="facts">
              <li><span>Name</span><b>{env.environment}</b></li>
              <li><span>Tasks</span><b>{env.tasks.length}</b></li>
              <li><span>Driven by browser</span><b>{env.counts.browser_tasks}</b></li>
              <li><span>Guards</span><b>{env.counts.guards}</b></li>
              <li><span>Named cheats</span><b>{env.counts.cheats}</b></li>
              <li><span>Scores recorded</span><b className={scored ? "lit" : "off"}>{scored}</b></li>
              <li><span>Findings open</span><b>{open.length}</b></li>
              <li><span>Generated</span><b className="n">{env.generated_at}</b></li>
            </ul>
          </section>
          <section>
            <h2>Tables a guard reads</h2>
            <p className="rail-note">
              {writes.length ? writes.join(", ") : "No task in this book writes a row."}
            </p>
          </section>
          <section>
            <h2>The adversarial suite</h2>
            <p className="rail-note">
              {env.suite.expectations_held} of {env.suite.expectations_total} expectations held on{" "}
              {env.suite.last_run}, exit {env.suite.exit_code}.
            </p>
            {env.suite.command ? (
              <p className="rail-note" style={{ marginTop: 8, fontFamily: "var(--mono)", fontSize: "var(--fs-meta)", color: "var(--ink-4)", overflowWrap: "anywhere" }}>
                {env.suite.command}
              </p>
            ) : null}
          </section>
          <section>
            <h2>What the inks mean</h2>
            <Legend />
          </section>
        </>
      }
    >
      <ViewHead
        kick={env.product}
        title={env.title}
        src={
          <>
            <span><b>environment</b> {env.environment}</span>
            <span><b>product</b> <a className="lnk" href={env.product_url} rel="noreferrer">{env.product_url}</a></span>
            {env.table_prefix ? <span><b>tables</b> {env.table_prefix}</span> : null}
            <span><b>suite</b> {env.suite.last_run}</span>
          </>
        }
      >
        The grader restores this product to its seeded state, drives the named surface, then reads the rows the product
        wrote. Every guard below states what it checks in the product&apos;s own terms, and every cheat names the guard
        that refuses it.
      </ViewHead>

      {models.length ? (
        <>
          <Head2 title="Runs against this environment" count={`${models.length} recorded`} />
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Rail</th>
                  <th>Ran</th>
                  <th className="r">Rollouts per task</th>
                  <th className="r">Tasks completed</th>
                  <th className="r">Mean</th>
                </tr>
              </thead>
              <tbody>
                {models.map(([model, run]) => (
                  <tr key={model}>
                    <td className="nm">{model}</td>
                    <td className="mono">{run.rail || model}</td>
                    <td className="mono n">{run.ran_at || "not recorded"}</td>
                    <td className="fig">{run.rollouts_per_task ?? "not set"}</td>
                    <td className="fig">{run.tasks_completed ?? 0}/{run.tasks_total ?? env.tasks.length}</td>
                    <td className="score held">{typeof run.mean === "number" ? run.mean.toFixed(2) : "not set"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <>
          <Head2 title="Runs against this environment" count="none recorded" />
          <div className="void">
            <b>No model has been driven through this environment.</b> Its task book is gradable and its adversarial
            suite held {env.suite.expectations_held} of {env.suite.expectations_total} expectations on{" "}
            {env.suite.last_run}. The tasks below carry no score, and none is printed as a zero.
          </div>
        </>
      )}

      <Head2 title="The task book" say="Each task, its guards, and the cheats those guards refuse." count={`${env.tasks.length} tasks`} />
      <div className="tasks">
        {env.tasks.map((task) => {
          const entries = Object.entries(task.scores || {});
          return (
            <article className="task" key={task.id}>
              <div className="task-h">
                <div>
                  <p className="id">{task.id}</p>
                  <p className="say">{task.description}</p>
                </div>
                <div className="sc">
                  {entries.length ? (
                    entries.map(([model, raw]) => {
                      const score = toScore(raw);
                      return (
                        <span key={model} className="word">
                          <i className={score >= 1 ? "i-held" : "i-caught"} />
                          {model}
                          <b className={`score ${score >= 1 ? "held" : "caught"}`} style={{ fontWeight: 400 }}>{score.toFixed(2)}</b>
                        </span>
                      );
                    })
                  ) : (
                    <Chip tone="off">unrun</Chip>
                  )}
                </div>
              </div>
              <div className="task-route">
                <span>driven <b>{task.driven}</b></span>
                <span>route <b>{task.route}</b></span>
                <span>writes <b>{task.writes.length ? task.writes.join(", ") : "no row"}</b></span>
                <span>guards <b>{task.guards.length}</b></span>
                <span>cheats <b>{task.cheats.length}</b></span>
              </div>
              <div className="task-cols">
                <section>
                  <h4>Guards, {task.guards.length}</h4>
                  <ul className="rows">
                    {task.guards.map((guard) => (
                      <li key={guard.id}>
                        <code>{guard.id}</code>
                        <span>{guard.checks}</span>
                      </li>
                    ))}
                  </ul>
                </section>
                <section>
                  <h4>Cheats refused, {task.cheats.length}</h4>
                  <ul className="rows">
                    {task.cheats.map((cheat) => (
                      <li key={cheat.id}>
                        <code>{cheat.id}</code>
                        <span>{cheat.fakes}</span>
                        <span className="by">caught by <b>{cheat.caught_by}</b></span>
                      </li>
                    ))}
                  </ul>
                </section>
              </div>
            </article>
          );
        })}
      </div>

      {env.not_gradable.length ? (
        <>
          <Head2
            title="Not gradable, and why"
            say="Task-shaped routes that write no row a guard can read."
            count={`${env.not_gradable.length} recorded`}
          />
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Route or surface</th>
                  <th>Why it is out</th>
                </tr>
              </thead>
              <tbody>
                {env.not_gradable.map((ng) => (
                  <tr key={ng.what}>
                    <td className="mono">{ng.what}</td>
                    <td style={{ color: "var(--ink-3)" }}>{ng.why}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      {env.defects.length ? (
        <>
          <Head2
            title="Findings"
            say="Defects the environment build found in the product itself."
            count={`${open.length} open of ${env.defects.length}`}
          />
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>State</th>
                  <th>Severity</th>
                  <th>Where</th>
                  <th>What was found</th>
                </tr>
              </thead>
              <tbody>
                {env.defects.map((defect, i) => (
                  <tr key={`${defect.where}-${i}`}>
                    <td>
                      <Chip tone={defect.fixed ? "ok" : "open"}>{defect.fixed ? "fixed" : "open"}</Chip>
                    </td>
                    <td className="mono">{defect.severity}</td>
                    <td className="mono" style={{ overflowWrap: "anywhere" }}>{defect.where}</td>
                    <td style={{ color: "var(--ink-3)" }}>{defect.summary}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </Shell>
  );
}
