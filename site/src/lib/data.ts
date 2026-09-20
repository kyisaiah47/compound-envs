import fs from "node:fs";
import path from "node:path";

export type Guard = { id: string; checks: string };
export type Cheat = { id: string; fakes: string; caught_by: string };
export type RawScore = number | { score?: number; passed?: boolean };
export type Task = {
  id: string;
  description: string;
  driven: string;
  route: string;
  writes: string[];
  guards: Guard[];
  cheats: Cheat[];
  scores: Record<string, RawScore>;
};
export type Defect = { summary: string; where: string; severity: string; fixed: boolean };
export type NotGradable = { what: string; why: string };
export type ModelRun = {
  ran_at?: string;
  rail?: string;
  rollouts_per_task?: number;
  mean?: number;
  tasks_completed?: number;
  tasks_total?: number;
  complete?: boolean;
};
export type Environment = {
  product: string;
  environment: string;
  title: string;
  product_url: string;
  product_repo?: string;
  table_prefix?: string;
  generated_at: string;
  verdict: string;
  tasks: Task[];
  not_gradable: NotGradable[];
  defects: Defect[];
  suite: { command?: string; expectations_total: number; expectations_held: number; exit_code: number; last_run: string };
  counts: { tasks: number; cheats: number; guards: number; browser_tasks: number };
  models: Record<string, ModelRun>;
};

export function toScore(raw: RawScore): number {
  if (typeof raw === "number") return raw;
  if (typeof raw?.score === "number") return raw.score;
  return raw?.passed ? 1 : 0;
}

let cache: Environment[] | null = null;

export function getEnvironments(): Environment[] {
  if (cache) return cache;
  const root = path.resolve(process.cwd(), "..", "envs");
  cache = fs
    .readdirSync(root)
    .map((name) => path.join(root, name, "results.json"))
    .filter((file) => fs.existsSync(file))
    .map((file) => {
      const env = JSON.parse(fs.readFileSync(file, "utf8")) as Environment;
      env.not_gradable ||= [];
      env.defects ||= [];
      env.models ||= {};
      return env;
    })
    .sort((a, b) => a.product.localeCompare(b.product));
  return cache;
}

export function getEnvironment(product: string) {
  return getEnvironments().find((env) => env.product === product);
}

/** Tasks in this environment that carry a score from at least one model. */
export function scoredCount(env: Environment) {
  return env.tasks.filter((task) => Object.keys(task.scores || {}).length > 0).length;
}

export type ModelRow = {
  model: string;
  rail: string;
  ranAt: string;
  environments: number;
  scored: number;
  held: number;
  mean: number;
};

/** One row per model that has actually been run. A model with no recorded run has no row. */
export function modelRows(envs = getEnvironments()): ModelRow[] {
  const rows = new Map<string, ModelRow & { envSet: Set<string> }>();
  for (const env of envs) {
    for (const task of env.tasks) {
      for (const [model, raw] of Object.entries(task.scores || {})) {
        const run = env.models[model] || {};
        const row =
          rows.get(model) ||
          ({ model, rail: run.rail || model, ranAt: run.ran_at || "", environments: 0, scored: 0, held: 0, mean: 0, envSet: new Set<string>() } as ModelRow & { envSet: Set<string> });
        row.envSet.add(env.product);
        row.scored += 1;
        row.held += toScore(raw) >= 1 ? 1 : 0;
        if (run.ran_at && run.ran_at > row.ranAt) row.ranAt = run.ran_at;
        rows.set(model, row);
      }
    }
  }
  return [...rows.values()]
    .map(({ envSet, ...row }) => ({ ...row, environments: envSet.size, mean: row.scored ? row.held / row.scored : 0 }))
    .sort((a, b) => b.mean - a.mean || b.scored - a.scored);
}

export type ScoreLine = {
  product: string;
  title: string;
  task: Task;
  model: string;
  score: number;
};

/** Every recorded score, one line each, newest environment first by product name. */
export function scoreLines(envs = getEnvironments()): ScoreLine[] {
  const lines: ScoreLine[] = [];
  for (const env of envs) {
    for (const task of env.tasks) {
      for (const [model, raw] of Object.entries(task.scores || {})) {
        lines.push({ product: env.product, title: env.title, task, model, score: toScore(raw) });
      }
    }
  }
  return lines;
}

export function totals(envs = getEnvironments()) {
  return envs.reduce(
    (sum, env) => ({
      environments: sum.environments + 1,
      tasks: sum.tasks + env.tasks.length,
      guards: sum.guards + env.counts.guards,
      cheats: sum.cheats + env.counts.cheats,
      browser: sum.browser + env.counts.browser_tasks,
      held: sum.held + env.suite.expectations_held,
      expected: sum.expected + env.suite.expectations_total,
      scored: sum.scored + env.tasks.reduce((n, t) => n + Object.keys(t.scores || {}).length, 0),
      defects: sum.defects + env.defects.length,
      open: sum.open + env.defects.filter((d) => !d.fixed).length,
      notGradable: sum.notGradable + env.not_gradable.length,
    }),
    { environments: 0, tasks: 0, guards: 0, cheats: 0, browser: 0, held: 0, expected: 0, scored: 0, defects: 0, open: 0, notGradable: 0 },
  );
}

export function lastProved(envs = getEnvironments()) {
  return envs.map((env) => env.suite.last_run).filter(Boolean).sort().at(-1) || "never";
}
