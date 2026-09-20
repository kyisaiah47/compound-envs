import Link from "next/link";
import Reveal from "@/components/Reveal";
import { Chip, RailMk, Legend, Mk, SecHead, Shell, ViewHead } from "@/components/Shell";
import { getEnvironments, lastProved, modelRows, scoreLines, scoredCount, toScore, totals } from "@/lib/data";

export const dynamic = "force-static";

export default function ScorecardPage() {
  const envs = getEnvironments();
  const all = totals(envs);
  const models = modelRows(envs);
  const lines = scoreLines(envs);
  const ran = envs.filter((env) => scoredCount(env) > 0);
  const unrun = envs.filter((env) => scoredCount(env) === 0);
  const proved = lastProved(envs);

  return (
    <Shell
      active="scorecard"
      envs={envs}
      claim={
        <>
          {all.scored} of {all.tasks} tasks carry a recorded score. The other {all.tasks - all.scored} have never been
          run, and this page prints no figure for them.
        </>
      }
      stamps={
        <>
          <span className="stamp">Models run <b>{models.length}</b></span>
          <span className="stamp">Proved <b className="n">{proved}</b></span>
        </>
      }
      rail={
        <>
          <div className="grp">
            <h3>How a score is made</h3>
            <ol className="steps">
              <li><b>Reset</b><span>The environment is restored to its seeded state, so two runs start identical.</span></li>
              <li><b>Drive</b><span>The model works through the product&apos;s own browser surface or API route.</span></li>
              <li><b>Grade</b><span>Each guard queries the rows the product wrote and holds or refuses.</span></li>
              <li><b>Record</b><span>The score is written beside the task it came from. Nothing is averaged away.</span></li>
            </ol>
          </div>
          <div className="grp">
            <h3>What the states mean</h3>
            <Legend />
          </div>
          <div className="grp">
            <h3>The ledger</h3>
            <ul className="facts">
              <li><span>Environments</span><b>{all.environments}</b></li>
              <li><span>Tasks</span><b>{all.tasks}</b></li>
              <li><span>Driven by browser</span><b>{all.browser}</b></li>
              <li><span>Guards</span><b>{all.guards}</b></li>
              <li><span>Named cheats</span><b>{all.cheats}</b></li>
              <li><span>Scores recorded</span><b>{all.scored}</b></li>
              <li><span>Tasks never run</span><b className="off">{all.tasks - all.scored}</b></li>
              <li><span>Findings open</span><b>{all.open}</b></li>
            </ul>
          </div>
        </>
      }
    >
      <ViewHead
        kick="Scorecard"
        icon="squares-four"
        title="What a model actually left in the database"
        src={
          <>
            <span><b>source</b> envs/*/results.json</span>
            <span><b>schema</b> compound-evals/results@1</span>
            <span><b>method</b> reset, drive, grade</span>
          </>
        }
      >
        Each score below came from driving one model through one product task and then reading the rows the product
        wrote. A guard holds when the state is what the task asked for. It refuses when the state looks right on screen
        and is wrong underneath.
      </ViewHead>

      <Reveal as="section" className="sec">
        <SecHead title="Models run" say="One row per model that has been driven through an environment." count={`${models.length} recorded`} />
        {models.length ? (
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Rail</th>
                  <th>Last run</th>
                  <th className="r">Environments</th>
                  <th className="r">Tasks scored</th>
                  <th className="r">Guards held</th>
                  <th className="r">Mean</th>
                </tr>
              </thead>
              <tbody>
                {models.map((row) => (
                  <tr key={row.model}>
                    <td className="nm"><RailMk rail={row.model} /><span>{row.model}</span></td>
                    <td className="mn">{row.rail}</td>
                    <td className="mn n">{row.ranAt || "not recorded"}</td>
                    <td className="fig">{row.environments}</td>
                    <td className="fig">{row.scored}</td>
                    <td className="fig">{row.held}</td>
                    <td className="score held">{row.mean.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="void">
            <b>No model has been driven through an environment yet.</b> The graders are proved and the tasks are ready.
            This table fills in from task scores on the first recorded run.
          </div>
        )}
      </Reveal>

      {lines.length ? (
        <Reveal as="section" className="sec">
          <SecHead title="Every recorded score" say="One line per task, per model. Nothing is rolled up." count={`${lines.length} lines`} />
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Environment</th>
                  <th>Task</th>
                  <th>Driven</th>
                  <th>Model</th>
                  <th className="r">Score</th>
                  <th className="r">Verdict</th>
                </tr>
              </thead>
              <tbody>
                {lines.map((line) => (
                  <tr key={`${line.product}/${line.task.id}/${line.model}`}>
                    <td>
                      <Link className="nm" href={`/${line.product}`}>
                        <Mk slug={line.product} />
                        <span>{line.product}</span>
                      </Link>
                    </td>
                    <td>
                      <span className="tsk">
                        <b>{line.task.id}</b>
                        <span>{line.task.description}</span>
                        <em>{line.task.route}</em>
                      </span>
                    </td>
                    <td className="mn">{line.task.driven}</td>
                    <td className="mn">{line.model}</td>
                    <td className={`score ${line.score >= 1 ? "held" : "caught"}`}>{line.score.toFixed(2)}</td>
                    <td className="r">
                      <Chip tone={line.score >= 1 ? "held" : "caught"}>{line.score >= 1 ? "held" : "caught"}</Chip>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Reveal>
      ) : null}

      {ran.length ? (
        <Reveal as="section" className="sec">
          <SecHead title="Environments with a run" say="Coverage inside an environment, counted in tasks." count={`${ran.length} of ${envs.length}`} />
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Environment</th>
                  <th className="r">Tasks</th>
                  <th className="r">Scored</th>
                  <th className="r">Held</th>
                  <th className="r">Mean</th>
                </tr>
              </thead>
              <tbody>
                {ran.map((env) => {
                  const scored = scoredCount(env);
                  const held = env.tasks.filter((t) => Object.values(t.scores || {}).some((s) => toScore(s) >= 1)).length;
                  return (
                    <tr key={env.product}>
                      <td>
                        <Link className="nm" href={`/${env.product}`}>
                          <Mk slug={env.product} />
                          <span>{env.product}</span>
                          <small>{env.title}</small>
                        </Link>
                      </td>
                      <td className="fig">{env.tasks.length}</td>
                      <td className="fig">{scored}</td>
                      <td className="fig">{held}</td>
                      <td className="score held">{(held / scored).toFixed(2)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Reveal>
      ) : null}

      <Reveal as="section" className="sec">
        <SecHead title="Waiting on a run" say="Built, proved, and never driven." count={`${unrun.length} environments`} />
        <p className="note">
          Each of these ships a gradable task book and an adversarial suite that already passes. No model has been
          driven through them, so they carry no score and no estimate.
        </p>
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Environment</th>
                <th className="r">Tasks</th>
                <th className="r">Guards</th>
                <th className="r">Cheats</th>
                <th className="r">Graders</th>
                <th className="r">Score</th>
              </tr>
            </thead>
            <tbody>
              {unrun.map((env) => (
                <tr key={env.product}>
                  <td>
                    <Link className="nm" href={`/${env.product}`}>
                      <Mk slug={env.product} />
                      <span>{env.product}</span>
                      <small>{env.title}</small>
                    </Link>
                  </td>
                  <td className="fig">{env.tasks.length}</td>
                  <td className="fig">{env.counts.guards}</td>
                  <td className="fig">{env.counts.cheats}</td>
                  <td className="fig">{env.suite.expectations_held}/{env.suite.expectations_total}</td>
                  <td className="score unrun">unrun</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Reveal>
    </Shell>
  );
}
