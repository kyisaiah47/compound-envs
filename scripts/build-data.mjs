#!/usr/bin/env node
/* THE ENVIRONMENTS, COMPILED INTO THE BUNDLE.
 *
 * ⛔ THE CONSOLE MAY NOT READ THE FILESYSTEM AT REQUEST TIME. It is served by a Cloudflare
 * Worker, which has no filesystem: `fs.readdirSync` threw
 * `no such file or directory, readdir '/envs'` on every route and the whole site answered 500,
 * measured in local workerd on 2026-09-20. Prerendering is not a defence, because the server
 * bundle still evaluates the route module on a cold start.
 *
 * So the read happens HERE, at build time, on the machine that has the files, and the console
 * imports the result as an ordinary module. 24 results.json files, about 572K.
 */
import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const ENVS = path.join(ROOT, 'envs');
const OUT = path.join(ROOT, 'src', 'data', 'environments.json');

if (!fs.existsSync(ENVS)) throw new Error(`build-data: no envs/ at ${ENVS}`);

const environments = fs
  .readdirSync(ENVS)
  .map((name) => path.join(ENVS, name, 'results.json'))
  .filter((file) => fs.existsSync(file))
  .map((file) => {
    const env = JSON.parse(fs.readFileSync(file, 'utf8'));
    env.not_gradable ||= [];
    env.defects ||= [];
    env.models ||= {};
    return env;
  })
  .sort((a, b) => a.product.localeCompare(b.product));

if (!environments.length) throw new Error('build-data: envs/ holds no results.json');

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify(environments));
const scored = environments.reduce(
  (n, e) => n + e.tasks.reduce((m, t) => m + Object.keys(t.scores || {}).length, 0),
  0,
);
console.log(`build-data: ${environments.length} environments, ${scored} scores -> src/data/environments.json`);
